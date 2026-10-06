"""H03 单 HKJC 原件基础资料旁路；不取源、不造身份、不发布。

调用方负责绑定可信 H01/expectedSHA/实体版本；哈希不代替来源许可。
仅串行化本旁路，旧身份写者的全局并发安全仍需共享合同。
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from stable.models import (
    HorseProfile, HorseProfileCandidateStatus, HorseProfileDataCandidate,
    HorseProfileModule, HorseProfileStatus,
)
from . import horse_profile_publish, horse_profiles
from .horse_cache_reuse import plan_cache_reuse
from .horse_source_cache_reuse_adapter import adapt_hkjc_source_cache
from .horse_target_inventory import _key, _plain, _sha, _time

BASIC_FIELDS = ("country", "sex", "color", "birth_date", "owner_name", "trainer_name", "breeder_name")
SOURCE_ROLE = "h03_hkjc_basic_cache.v1"


def _blocked(reason):
    return {"status": "blocked", "reason": reason, "published": False}


def _json_safe(value, depth=0):
    if depth > 64:
        raise ValueError("audit_structure_limit")
    if type(value) in (date, datetime):
        return value.isoformat()
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("audit_structure")
        return {key: _json_safe(item, depth + 1) for key, item in value.items()}
    if type(value) is list:
        return [_json_safe(item, depth + 1) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("audit_structure")


def _baseline(value):
    parsed = value if type(value) is datetime else _time(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("baseline_timezone")
    return parsed.astimezone(timezone.utc)


def _keys(refs, field):
    if type(refs) is not dict:
        raise ValueError("identity_provenance")
    values = refs.get(field, [])
    if type(values) is not list:
        raise ValueError("identity_provenance")
    for value in values:
        _key(value)
        if ":" not in value or not all(value.split(":", 1)):
            raise ValueError("identity_provenance")
    return values


def _identity_reason(profile, proof):
    try:
        verified = _keys(profile.source_refs, "horse_identity_verified_keys")
        flat = _keys(profile.source_refs, "horse_identity_keys")
    except ValueError:
        return "identity_provenance"
    normalized = [key.casefold() for key in verified]
    if len(normalized) != len(set(normalized)):
        return "identity_ambiguous"
    expected = {row["horse_key"].casefold() for row in proof}
    if not expected or not expected <= set(normalized):
        return "strong_identity_missing"
    all_keys = {key.casefold() for key in verified + flat}
    for key in expected:
        namespace = key.split(":", 1)[0] + ":"
        if any(item.startswith(namespace) and item != key for item in all_keys):
            return "identity_conflict"
    # Case-insensitive prefilter plus exact normalized array comparison. This is
    # a bounded local conflict check, not a global uniqueness/concurrency claim.
    query = Q()
    for key in sorted(expected):
        query |= Q(source_refs__horse_identity_verified_keys__icontains=key)
    others = list(HorseProfile.objects.exclude(pk=profile.pk).filter(query)
                  .values_list("source_refs", flat=True)[:101])
    if len(others) > 100:
        return "identity_conflict_check_limit"
    for refs in others:
        try:
            other_keys = _keys(refs, "horse_identity_verified_keys")
        except ValueError:
            return "identity_ambiguous"
        if expected & {key.casefold() for key in other_keys}:
            return "identity_conflict"
    return None


def _gate(profile):
    gate = horse_profile_publish.evaluate_basic_publish_gate(profile)
    return {"eligible": gate.eligible, "blocking_reasons": list(gate.blocking_reasons)}


def apply_basic_profile_from_cache(
    *, snapshot, candidate, raw_bytes, expected_sha256, ref, source_ref,
    entity_versions, as_of, max_age_seconds, expected_updated_at, actor,
):
    """校验→锁后安全检查→已消费版本→新基线→现有 writer，整片原子。

    无效输入返回 blocked；数据库/save/apply/log 异常向外传播并回滚，
    不把系统故障误当已成功，也不自动重试/抓取或切换身份。
    """
    try:
        if type(candidate) is not dict:
            return _blocked("candidate_shape")
        _plain(candidate)
        record = adapt_hkjc_source_cache(
            raw_bytes, expected_sha256=expected_sha256, ref=ref, source_ref=source_ref,
        )
        plan = plan_cache_reuse(snapshot, [record], entity_versions,
                                as_of=as_of, max_age_seconds=max_age_seconds)
        matches = [item for item in plan["candidates"]
                   if item["entity_key"] == candidate.get("entity_key")]
        if len(matches) != 1 or _sha(matches[0]) != _sha(candidate):
            return _blocked("candidate_mismatch")
        checked = matches[0]
        if checked["action"] != "reusable" or checked["cache_refs"] != [ref]:
            return _blocked("cache_not_reusable")
        entity_key = checked["entity_key"]
        if not entity_key.startswith("profile:"):
            return _blocked("existing_profile_required")
        profile_id = int(entity_key.removeprefix("profile:"))
        if profile_id < 1 or profile_id > 10**12 or entity_key != f"profile:{profile_id}":
            return _blocked("profile_key")
        baseline = _baseline(expected_updated_at)
        if not isinstance(actor, get_user_model()) or actor.pk is None:
            return _blocked("local_actor_required")
        source = json.loads(record["content"])
        basic = source["basic_profile"]
        payload = {}
        for field in BASIC_FIELDS:
            value = basic[field]
            if type(value) is not str or not value.strip():
                return _blocked("basic_field_empty")
            if field == "birth_date":
                value = date.fromisoformat(value.strip())
            else:
                model_field = HorseProfile._meta.get_field(field)
                if len(value) > model_field.max_length:
                    return _blocked("basic_field_length")
            HorseProfile._meta.get_field(field).clean(value, None)
            payload[field] = value
        input_sha = _sha({
            "candidate": checked, "snapshot_sha": _sha(snapshot),
            "entity_versions": entity_versions, "as_of": as_of,
            "max_age_seconds": max_age_seconds, "expected_updated_at": baseline.isoformat(),
            "source_role": SOURCE_ROLE,
        })
    except (ValueError, TypeError, KeyError, ValidationError, RecursionError):
        return _blocked("input_invalid")

    with transaction.atomic():
        profile = (HorseProfile.objects.select_related("primary_term")
                   .select_for_update(of=("self",)).filter(pk=profile_id).first())
        if profile is None:
            return _blocked("target_missing")
        if profile.review_status not in (HorseProfileStatus.DRAFT, HorseProfileStatus.READY) or profile.hidden_at is not None:
            return _blocked("target_not_private")
        reason = _identity_reason(profile, checked["identity_evidence"])
        if reason:
            return _blocked(reason)
        consumed = list(HorseProfileDataCandidate.objects.filter(
            profile=profile, module=HorseProfileModule.PROFILE, source_name=SOURCE_ROLE,
            raw_payload__h02_idempotency_key=checked["idempotency_key"],
        )[:2])
        if len(consumed) > 1:
            return _blocked("consumption_ambiguous")
        if consumed:
            existing = consumed[0]
            if existing.raw_payload.get("input_sha256") != input_sha:
                return _blocked("version_content_conflict")
            if existing.status != HorseProfileCandidateStatus.APPLIED:
                return _blocked("consumption_not_applied")
            result = existing.raw_payload.get("h03_result")
            if type(result) is not dict or result.get("candidate_id") != existing.pk:
                return _blocked("consumption_receipt_invalid")
            result = deepcopy(result)
            result.update(status="already_applied", publish_gate=_gate(profile))
            return result
        # Deliberately after consumed-key handling: original request retries
        # keep their old baseline even when the first write advanced updated_at.
        if profile.updated_at != baseline:
            return _blocked("stale_baseline")
        before = _json_safe({field: getattr(profile, field) for field in BASIC_FIELDS})
        audit = {
            "schema_version": SOURCE_ROLE, "h02_idempotency_key": checked["idempotency_key"],
            "input_sha256": input_sha, "entity_key": entity_key,
            "entity_version": checked["entity_version"],
            "content_sha256": record["content_sha256"],
            "source_time": record["source_time"], "source_ref": source_ref, "cache_ref": ref,
            "source_url": source["source"]["url"], "expected_updated_at": baseline.isoformat(),
            "identity_evidence": checked["identity_evidence"],
            "inventory_sha256": plan["inventory_sha256"], "h02_plan_sha256": plan["content_sha256"],
            "as_of": as_of, "max_age_seconds": max_age_seconds,
        }
        stored = HorseProfileDataCandidate.objects.create(
            profile=profile, module=HorseProfileModule.PROFILE, source_name=SOURCE_ROLE,
            source_url=source["source"]["url"], candidate_payload=_json_safe(payload),
            diff_payload=_json_safe(horse_profiles.build_candidate_diff(profile, HorseProfileModule.PROFILE, payload)),
            raw_payload=_json_safe(audit), confidence=0,
        )
        # Save ISO JSON first, then apply typed date on the same in-memory row.
        # Existing apply only persists status/applied metadata, not this payload.
        stored.candidate_payload = payload
        applied = horse_profiles.apply_data_candidate(stored, user=actor)
        result = {
            "status": "applied", "published": False, "candidate_id": stored.pk,
            "input_sha256": input_sha, "source_time": record["source_time"],
            "before": before,
            "after": _json_safe({field: getattr(profile, field) for field in BASIC_FIELDS}),
            "skipped_locked": applied["skipped_locked"], "updated_fields": applied["updated_fields"],
            "publish_gate": _gate(profile),
        }
        stored.raw_payload["h03_result"] = _json_safe(result)
        stored.save(update_fields=["raw_payload", "updated_at"])
        return result

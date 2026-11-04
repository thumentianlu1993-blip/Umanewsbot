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

    return _apply_prepared_basic(
        profile_id=profile_id, checked=checked, baseline=baseline, payload=payload,
        input_sha=input_sha, actor=actor, record=record, source=source,
        source_ref=source_ref, ref=ref, plan=plan, as_of=as_of,
        max_age_seconds=max_age_seconds, source_role=SOURCE_ROLE,
    )


def _apply_prepared_basic(*, profile_id, checked, baseline, payload, input_sha,
                          actor, record, source, source_ref, ref, plan, as_of,
                          max_age_seconds, source_role=SOURCE_ROLE):
    entity_key = checked["entity_key"]
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
            profile=profile, module=HorseProfileModule.PROFILE, source_name=source_role,
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
            "schema_version": source_role, "h02_idempotency_key": checked["idempotency_key"],
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
            profile=profile, module=HorseProfileModule.PROFILE, source_name=source_role,
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


def consume_reviewed_basic_module(request):
    """许可权威合同缺位：所有请求恒拒绝，不读DB、委派或模拟应用。"""
    return dict(status='blocked', reason='permission_authority_unavailable', applied=False,
                committed=False, published=False, candidate_id=None)


BASIC_MODULE_TRANSACTION_ROLE = 'h03_hkjc_basic_module.v1'
BASIC_MODULE_TRANSACTION_LABELS = {
    'transaction_capability_only': True, 'source_permission_status': 'not_evaluated',
    'public_consumer_authorized': False,
}


def _basic_module_reject(reason):
    from django.core.management.base import CommandError
    raise CommandError(reason) from None


def _basic_module_now():
    from django.utils import timezone as django_timezone
    return django_timezone.now()


def _basic_module_inputs(*, packet_raw, source_raw, module_raw, permission_raw,
                         reviewed_raw, expected_review_sha256, actor_id, code_sha):
    """真实producer/H02/prepare和独立审决策重建；许可引用不变为grant。"""
    import hashlib
    import re
    from . import horse_basic_profile_prepare_input as inputs
    from . import horse_source_cache_reuse_adapter as producer

    originals = dict(packet=packet_raw, source=source_raw, module=module_raw, permission=permission_raw)
    if any(type(raw) is not bytes or len(raw) > inputs.MAX_BYTES for raw in [*originals.values(), reviewed_raw]):
        _basic_module_reject('module_input_bytes')
    if (type(actor_id) is not int or not 0 < actor_id <= 10**12
            or type(code_sha) is not str or not re.fullmatch('[0-9a-f]{40}', code_sha)):
        _basic_module_reject('module_execution_arguments')
    inputs._bound(reviewed_raw, expected_review_sha256, 'module_review_digest', 'module_review_hash')
    review = inputs._strict_json(reviewed_raw)
    fields = {'schema_version', 'code_sha', 'producer_version', 'inputs', 'target',
              'scope', 'module_reviews', 'reviewer_id', 'before', 'after'}
    if (type(review) is not dict or set(review) != fields
            or review['schema_version'] != 'h03-basic-module-reviewed-input.v1'
            or review['producer_version'] != producer.BASIC_MODULE_PRODUCER_VERSION
            or review['code_sha'] != code_sha or type(review['reviewer_id']) is not int
            or review['reviewer_id'] != actor_id):
        _basic_module_reject('module_review_binding')
    bindings = review['inputs']
    if type(bindings) is not dict or set(bindings) != set(originals):
        _basic_module_reject('module_review_inputs')
    paths = []
    for name, raw in originals.items():
        item = bindings[name]
        if type(item) is not dict or set(item) != {'path', 'sha256'}:
            _basic_module_reject('module_review_inputs')
        inputs._parts(item['path'], 'module_review_path')
        inputs._bound(raw, item['sha256'], 'module_review_input_digest', 'module_review_input_hash')
        paths.append(item['path'])
    if len(set(paths)) != len(paths):
        _basic_module_reject('module_review_input_alias')
    packet = inputs._strict_basic_module_packet(packet_raw)
    if (bindings['source']['path'] != packet['source_file']
            or bindings['permission']['path'] != packet['permission_file']):
        _basic_module_reject('module_review_source_path')
    module, plan, candidate = inputs._prepare_basic_module(
        packet, source_raw, packet['expected_source_sha256'], permission_raw=permission_raw)
    if module_raw != producer._basic_module_canonical(module):
        _basic_module_reject('module_projection_bytes')
    digests = {name + '_sha256': hashlib.sha256(raw).hexdigest() for name, raw in originals.items()}
    digests['projection_sha256'] = module['projection_sha256']
    profile_id = int(candidate['entity_key'].removeprefix('profile:'))
    target = dict(profile_id=profile_id, entity_key=candidate['entity_key'],
                  entity_version=candidate['entity_version'], profile_baseline=packet['profile_baseline'],
                  h02_plan_sha256=plan['content_sha256'], candidate_idempotency_key=candidate['idempotency_key'],
                  module_content_sha256=digests['module_sha256'], projection_sha256=digests['projection_sha256'],
                  source_sha256=digests['source_sha256'], permission_sha256=digests['permission_sha256'])
    if (type(review['target']) is not dict or _sha(review['target']) != _sha(target)
            or review['scope'] != dict(module='profile', fields=list(BASIC_FIELDS))
            or type(review['module_reviews']) is not dict or set(review['module_reviews']) != {'profile'}):
        _basic_module_reject('module_review_target')
    metadata = review['module_reviews']['profile']
    if (type(metadata) is not dict or set(metadata) != {'status', 'reviewed_by', 'approved_at', 'decision_source_reference'}
            or metadata['status'] not in ('approved', 'ignore')
            or any(type(value) is not str or not value.strip() for value in metadata.values())):
        _basic_module_reject('module_review_metadata')
    approved = inputs._utc(metadata['approved_at'], 'module_review_time')
    for key in ('before', 'after'):
        values = review[key]
        if type(values) is not dict or set(values) != set(BASIC_FIELDS):
            _basic_module_reject('module_review_fields')
        if any(type(value) is not str and not (field == 'birth_date' and value is None)
               for field, value in values.items()):
            _basic_module_reject('module_review_fields')
    if review['after'] != module['projection']:
        _basic_module_reject('module_review_after')
    binding = dict(review_sha256=expected_review_sha256, decision=review)
    baseline = inputs._utc(packet['profile_baseline'], 'module_profile_baseline')
    input_sha = _sha(dict(source_role=BASIC_MODULE_TRANSACTION_ROLE, binding=binding, digests=digests,
                          candidate=candidate, snapshot_sha=_sha(packet['snapshot']),
                          entity_versions=packet['entity_versions'], as_of=packet['as_of'],
                          max_age_seconds=packet['max_age_seconds'], expected_updated_at=baseline.isoformat()))
    payload = dict(module['projection'])
    payload['birth_date'] = date.fromisoformat(payload['birth_date'])
    return dict(packet=packet, module=module, plan=plan, candidate=candidate, review=review,
                metadata=metadata, approved=approved, profile_id=profile_id, baseline=baseline,
                source=inputs._strict_json(source_raw, allow_float=True), payload=payload,
                binding=binding, digests=digests, input_sha=input_sha)


def _basic_module_freshness(bundle):
    now = _baseline(_basic_module_now())
    source = _time(bundle['module']['source_binding']['fetched_at'])
    as_of = _time(bundle['packet']['as_of'])
    if source > now or as_of > now:
        _basic_module_reject('source_or_packet_future')
    if (now - source).total_seconds() > bundle['packet']['max_age_seconds']:
        _basic_module_reject('source_expired')
    if bundle['approved'] > now:
        _basic_module_reject('review_future')


def _basic_module_actor(actor, bundle):
    if actor is None or not actor.is_active or not actor.is_staff:
        _basic_module_reject('actor_not_staff')
    if actor.get_username() != bundle['metadata']['reviewed_by']:
        _basic_module_reject('module_review_actor')


def _basic_module_profile(profile, bundle):
    if profile is None:
        _basic_module_reject('target_missing')
    if profile.review_status not in (HorseProfileStatus.DRAFT, HorseProfileStatus.READY) or profile.hidden_at is not None:
        _basic_module_reject('target_not_private')
    reason = _identity_reason(profile, bundle['candidate']['identity_evidence'])
    if reason:
        _basic_module_reject(reason)


def _basic_module_candidate(stored, bundle, actor):
    if (stored.status != HorseProfileCandidateStatus.APPLIED or stored.applied_by_id != actor.pk
            or stored.applied_at is None or stored.candidate_payload != bundle['module']['projection']
            or stored.source_url != bundle['source']['source']['url']):
        _basic_module_reject('module_candidate_readback')
    if stored.raw_payload.get('input_sha256') != bundle['input_sha']:
        _basic_module_reject('version_content_conflict')
    if _sha(stored.raw_payload.get('module_transaction_binding')) != _sha(bundle['binding']):
        _basic_module_reject('module_review_binding')
    if any(stored.raw_payload.get(key) != value for key, value in bundle['digests'].items()):
        _basic_module_reject('module_audit_binding')
    if _sha({key: stored.raw_payload.get(key) for key in BASIC_MODULE_TRANSACTION_LABELS}) != _sha(BASIC_MODULE_TRANSACTION_LABELS):
        _basic_module_reject('module_audit_labels')


def _apply_basic_module_transaction(*, packet_raw, source_raw, module_raw, permission_raw,
                                    reviewed_raw, expected_review_sha256, actor_id, code_sha, dry_run=False):
    """仅隔离PG机制：无公共调用/许可授予。下划线不构成安全沙箱。"""
    from django.db import connection
    from stable.models import OperationLog

    if type(dry_run) is not bool:
        _basic_module_reject('module_execution_arguments')
    if connection.vendor != 'postgresql':
        _basic_module_reject('postgresql_required')
    bundle = _basic_module_inputs(packet_raw=packet_raw, source_raw=source_raw, module_raw=module_raw,
                                 permission_raw=permission_raw, reviewed_raw=reviewed_raw,
                                 expected_review_sha256=expected_review_sha256, actor_id=actor_id, code_sha=code_sha)
    _basic_module_freshness(bundle)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '15s'")
        actor = get_user_model().objects.select_for_update(no_key=True).filter(pk=actor_id).first()
        _basic_module_actor(actor, bundle)
        _basic_module_freshness(bundle)
        profile = HorseProfile.objects.select_for_update(of=('self',)).filter(pk=bundle['profile_id']).first()
        _basic_module_profile(profile, bundle)
        _basic_module_freshness(bundle)
        fields_before = _json_safe({field: getattr(profile, field) for field in BASIC_FIELDS})
        if bundle['metadata']['status'] == 'ignore':
            if profile.updated_at != bundle['baseline']:
                _basic_module_reject('stale_baseline')
            if fields_before != bundle['review']['before']:
                _basic_module_reject('module_review_before')
            _basic_module_freshness(bundle)
            return dict(status='ignored', committed=False, published=False, candidate_id=None,
                        **BASIC_MODULE_TRANSACTION_LABELS)
        consumed = list(HorseProfileDataCandidate.objects.select_for_update().filter(
            profile=profile, module=HorseProfileModule.PROFILE, source_name=BASIC_MODULE_TRANSACTION_ROLE,
            raw_payload__h02_idempotency_key=bundle['candidate']['idempotency_key'])[:2])
        if len(consumed) > 1:
            _basic_module_reject('consumption_ambiguous')
        if consumed:
            # Digest priority matches the legacy consumed-before-baseline contract.
            if consumed[0].raw_payload.get('input_sha256') != bundle['input_sha']:
                _basic_module_reject('version_content_conflict')
            _basic_module_candidate(consumed[0], bundle, actor)
            old_result = consumed[0].raw_payload.get('h03_result')
            if (type(old_result) is not dict or old_result.get('candidate_id') != consumed[0].pk
                    or old_result.get('after') != fields_before):
                _basic_module_reject('module_replay_drift')
        else:
            if profile.updated_at != bundle['baseline']:
                _basic_module_reject('stale_baseline')
            if fields_before != bundle['review']['before']:
                _basic_module_reject('module_review_before')
        profile_before = HorseProfile.objects.filter(pk=profile.pk).values().get()
        records_before = list(profile.race_records.values().order_by('pk'))
        log_scope = dict(action_type='horse_candidate_applied', target_type='horse_profile', target_id=str(profile.pk))
        logs_before = set(OperationLog.objects.filter(**log_scope).values_list('pk', flat=True))
        locked = [field for field in BASIC_FIELDS if (profile.manual_lock_flags or {}).get(field)
                  or (profile.manual_lock_flags or {}).get(HorseProfileModule.PROFILE)]
        result = _apply_prepared_basic(
            profile_id=profile.pk, checked=bundle['candidate'], baseline=bundle['baseline'],
            payload=bundle['payload'], input_sha=bundle['input_sha'], actor=actor,
            record=bundle['candidate']['cache_evidence'][0], source=bundle['source'],
            source_ref=bundle['packet']['source_ref'], ref=bundle['candidate']['cache_refs'][0],
            plan=bundle['plan'], as_of=bundle['packet']['as_of'],
            max_age_seconds=bundle['packet']['max_age_seconds'], source_role=BASIC_MODULE_TRANSACTION_ROLE)
        if result.get('status') not in ('applied', 'already_applied'):
            _basic_module_reject(result.get('reason') or 'module_writer_blocked')
        stored = HorseProfileDataCandidate.objects.select_for_update().get(pk=result['candidate_id'])
        profile.refresh_from_db()
        actual = _json_safe({field: getattr(profile, field) for field in BASIC_FIELDS})
        expected = fields_before if consumed else {
            field: fields_before[field] if field in locked else bundle['module']['projection'][field]
            for field in BASIC_FIELDS}
        if (actual != expected or result.get('after') != actual or result.get('skipped_locked') != locked
                or stored.status != HorseProfileCandidateStatus.APPLIED
                or stored.candidate_payload != bundle['module']['projection']):
            _basic_module_reject('module_writer_readback')
        profile_after = HorseProfile.objects.filter(pk=profile.pk).values().get()
        if any(profile_after[key] != value for key, value in profile_before.items()
               if key not in {*BASIC_FIELDS, 'updated_at', 'completeness_status'}):
            _basic_module_reject('module_profile_protection')
        if list(profile.race_records.values().order_by('pk')) != records_before:
            _basic_module_reject('module_career_protection')
        new_logs = list(OperationLog.objects.filter(**log_scope).exclude(pk__in=logs_before))
        if consumed:
            if result['status'] != 'already_applied' or stored.pk != consumed[0].pk or new_logs:
                _basic_module_reject('module_replay_side_effect')
        elif (result['status'] != 'applied' or len(new_logs) != 1 or new_logs[0].admin_id != actor.pk
              or f"candidate={stored.pk} " not in new_logs[0].detail):
            _basic_module_reject('module_operation_log_missing')
        output = deepcopy(result)
        output.pop('publish_gate', None)
        output.update(BASIC_MODULE_TRANSACTION_LABELS, **bundle['digests'],
                      review_sha256=expected_review_sha256, committed=not bool(consumed))
        if not consumed:
            stored.raw_payload.update(bundle['digests'], **BASIC_MODULE_TRANSACTION_LABELS,
                                      module_transaction_binding=bundle['binding'], h03_result=_json_safe(output))
            stored.save(update_fields=['raw_payload', 'updated_at'])
            stored.refresh_from_db()
        _basic_module_candidate(stored, bundle, actor)
        actor.refresh_from_db()
        _basic_module_actor(actor, bundle)
        _basic_module_profile(profile, bundle)
        _basic_module_freshness(bundle)
        if dry_run:
            output.update(status='dry_run', simulated_status=result['status'], committed=False, candidate_id=None)
            transaction.set_rollback(True)
        # Keep serialization inside the atomic boundary; no persistence exception is swallowed.
        json.dumps(output, allow_nan=False)
        return output

"""隔离测试直接调用的独立履历行事务机制；不注册真实来源消费入口。

permission reference/hash 仅为审计锚，不构成来源 materialization 授权。
真实来源权威缺失，CLI/HTTP/task/staff/provider bridge 保持未注册。
下划线、staff/review 或数据库名称均不能代替实际隔离运行证据。
"""
from copy import deepcopy
from datetime import date
import json
import re

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from stable import models
from . import horse_race_records
from .horse_basic_profile_from_cache import _json_safe
from .horse_basic_profile_prepare_input import (
    MAX_BYTES, _bound, _equal, _parts, _reject, _strict_json, _strict_packet, _utc,
)
from .horse_career_record_from_review import (
    _counts, _profile_gate, _record_audit_state, _record_readback, _staff, _state,
)
from .horse_career_record_link_from_cache import PROFILE_DERIVED_FIELDS
from .horse_independent_career_row_prepare import _prepare_independent_career_row
from .operations import log_operation

SOURCE_ROLE = 'h03_hkjc_independent_career_row.v1'
REVIEW_SCHEMA = 'h03-independent-career-row-reviewed-input.v1'
REVIEW_FIELDS = {'schema_version', 'code_sha', 'inputs', 'target', 'binding',
                 'scope', 'module_reviews', 'reviewer_id', 'before', 'after'}
LABELS = dict(transaction_capability_only=True, source_permission_status='not_evaluated',
              public_consumer_authorized=False)


def _prepare(*, packet, source_raw, reviewed_raw, expected_source_sha256,
             selected_row_sha256, expected_review_sha256, actor_id, code_sha,
             permission_binding, dry_run):
    if any(type(raw) is not bytes or len(raw) > MAX_BYTES for raw in (packet, source_raw, reviewed_raw)):
        _reject('input_bytes_or_size')
    if (type(actor_id) is not int or actor_id <= 0 or type(dry_run) is not bool
            or type(code_sha) is not str or not re.fullmatch(r'[0-9a-f]{40}', code_sha)):
        _reject('execution_arguments')
    _bound(source_raw, expected_source_sha256, 'input_sha_invalid', 'input_sha_mismatch')
    _bound(reviewed_raw, expected_review_sha256, 'review_sha_invalid', 'review_sha_mismatch')
    review = _strict_json(reviewed_raw)
    if type(review) is not dict or set(review) != REVIEW_FIELDS or review['schema_version'] != REVIEW_SCHEMA:
        _reject('review_schema')
    _equal(review['code_sha'], code_sha, 'review_code_mismatch')
    if type(review['reviewer_id']) is not int or review['reviewer_id'] != actor_id:
        _reject('review_actor_mismatch')
    inputs = review['inputs']
    if type(inputs) is not dict or set(inputs) != {'packet', 'source'}:
        _reject('review_inputs')
    for key, raw in (('packet', packet), ('source', source_raw)):
        item = inputs[key]
        if type(item) is not dict or set(item) != {'path', 'sha256'}:
            _reject('review_inputs')
        _parts(item['path'], 'review_inputs')
        _bound(raw, item['sha256'], 'input_sha_invalid', 'input_sha_mismatch')
    checked = _strict_packet(packet)
    _equal(inputs['source']['path'], checked['source_file'], 'review_inputs')
    prepared = _prepare_independent_career_row(
        packet=packet, source_raw=source_raw, expected_source_sha256=expected_source_sha256,
        selected_row_sha256=selected_row_sha256, permission_binding=permission_binding)
    candidate = prepared['candidate']
    target = dict(profile_id=int(candidate['entity_key'].removeprefix('profile:')),
                  entity_key=candidate['entity_key'], entity_version=candidate['entity_version'],
                  profile_baseline=checked['profile_baseline'])
    _equal(review['target'], target, 'review_target_mismatch')
    _equal(review['scope'], dict(module='race_record', operation='create_unlinked',
        selected_row_sha=selected_row_sha256, event_id=None, result_id=None), 'review_scope_mismatch')
    _equal(review['binding'], prepared['binding'], 'review_binding_mismatch')
    selected = prepared['row_module']['selected_row']
    if review['before'] is not None:
        _reject('review_before_after_mismatch')
    _equal(review['after'], selected, 'review_before_after_mismatch')
    reviews = review['module_reviews']
    if type(reviews) is not dict or set(reviews) != {'race_record'}:
        _reject('review_module')
    decision = reviews['race_record']
    if (type(decision) is not dict or set(decision) !=
            {'status', 'reviewed_by', 'approved_at', 'decision_source_reference'}
            or decision['status'] not in ('approved', 'ignore')
            or any(type(decision[key]) is not str or not decision[key]
                   or any(ord(c) < 32 or ord(c) == 127 for c in decision[key])
                   for key in ('reviewed_by', 'decision_source_reference'))):
        _reject('review_module')
    _utc(decision['approved_at'], 'review_time')
    payload = deepcopy(prepared['writer_payload'])
    payload.update(race_date=date.fromisoformat(payload['race_date']), race_region='hong_kong',
                   raw_payload=deepcopy(selected), event_id=None, result_id=None)
    return dict(packet=checked, prepared=prepared, candidate=candidate, target=target,
                decision=review, review_sha256=expected_review_sha256, selected=selected,
                writer_payload=payload, source_time=prepared['row_module']['source_binding']['fetched_at'])


def _freshness(bundle):
    now = timezone.now()
    source = _utc(bundle['source_time'], 'source_time')
    packet = bundle['packet']
    if source > now or _utc(packet['as_of'], 'packet_time') > now:
        _reject('source_or_packet_future')
    if _utc(bundle['decision']['module_reviews']['race_record']['approved_at'], 'review_time') > now:
        _reject('review_future')
    if (now-source).total_seconds() > packet['max_age_seconds']:
        _reject('source_expired')


def _review_binding(bundle):
    return dict(reviewed_input_sha256=bundle['review_sha256'], decision=deepcopy(bundle['decision']))


def _payload(bundle):
    return _json_safe({'items': [bundle['writer_payload']]})


def _candidate_check(stored, actor, bundle, reason):
    if (stored.profile_id != bundle['target']['profile_id'] or stored.source_name != SOURCE_ROLE
            or stored.module != models.HorseProfileModule.RACE_RECORD
            or stored.status != models.HorseProfileCandidateStatus.APPLIED
            or stored.confidence != 0 or stored.applied_by_id != actor.pk or stored.applied_at is None):
        _reject(reason)
    _equal(stored.candidate_payload, _payload(bundle), reason)
    _equal(stored.source_url, bundle['writer_payload']['source_url'], reason)


def _operation_check(operation, stored, record, actor, profile):
    if operation is None or not isinstance(operation, models.OperationLog):
        _reject('operation_readback_mismatch')
    try:
        operation.refresh_from_db()
    except models.OperationLog.DoesNotExist:
        _reject('operation_readback_mismatch')
    if (operation.action_type != 'horse_candidate_applied' or operation.target_type != 'horse_profile'
            or operation.target_id != str(profile.pk) or operation.admin_id != actor.pk
            or operation.detail != f'已审私有独立履历 candidate={stored.pk} record={record.pk}'):
        _reject('operation_readback_mismatch')


def _result(stored, record_id, bundle, counts):
    return dict(status='applied', published=False, committed=True,
                candidate_id=stored.pk, record_id=record_id,
                entity_key=bundle['target']['entity_key'], review_input_sha256=bundle['review_sha256'],
                derived_counts=deepcopy(counts), **LABELS)


def _replay(stored, profile, actor, bundle):
    _candidate_check(stored, actor, bundle, 'consumption_binding_mismatch')
    audit = stored.raw_payload
    if type(audit) is not dict:
        _reject('consumption_binding_mismatch')
    expected = dict(schema_version=SOURCE_ROLE, prepared_binding=bundle['prepared']['binding'],
                    review_input_binding=_review_binding(bundle),
                    h02_idempotency_key=bundle['candidate']['idempotency_key'],
                    selected_row_sha=bundle['prepared']['binding']['selected_row_sha256'],
                    parent_career=bundle['prepared']['row_module']['coverage']['parent_career'])
    for key, value in expected.items():
        _equal(audit.get(key), value, 'consumption_binding_mismatch')
    result = audit.get('h03_result')
    if (type(result) is not dict or type(result.get('record_id')) is not int or result['record_id'] <= 0
            or type(audit.get('after_counts')) is not dict or type(audit.get('before_counts')) is not dict):
        _reject('consumption_binding_mismatch')
    _equal(result, _result(stored, result['record_id'], bundle, audit['after_counts']),
           'consumption_binding_mismatch')
    before = audit['before_counts']
    if (set(before) != {'records', 'collected_start_count', 'linked_race_event_count', 'unlinked_race_record_count'}
            or any(type(value) is not int or value < 0 for value in before.values())):
        _reject('consumption_binding_mismatch')
    _equal(audit['after_counts'], dict(before, records=before['records']+1,
        collected_start_count=before['collected_start_count']+1,
        unlinked_race_record_count=before['unlinked_race_record_count']+1), 'consumption_binding_mismatch')
    _equal(stored.diff_payload, {'record_id': {'before': None, 'after': result['record_id']},
        'counts': {'before': before, 'after': audit['after_counts']}}, 'consumption_binding_mismatch')
    record = models.HorseRaceRecord.objects.select_for_update(of=('self',)).filter(
        pk=result['record_id'], horse_profile=profile).first()
    if (record is None or record.event_id is not None or record.result_id is not None
            or record.start_status != 'started' or record.race_date_precision != 'exact'
            or record.normalization_issues):
        _reject('consumption_record_mismatch')
    _equal(_record_audit_state(record), audit.get('record_after'), 'consumption_record_mismatch')
    _equal(record.raw_payload, bundle['selected'], 'consumption_record_mismatch')
    if (not horse_race_records.race_record_matches_upsert_payload(record, bundle['writer_payload'])
            or record.idempotency_key != horse_race_records.record_idempotency_key(profile, bundle['writer_payload'])
            or record.canonical_race_key != horse_race_records.canonical_race_key(profile, bundle['writer_payload'])):
        _reject('consumption_record_mismatch')
    operation_id = audit.get('operation_id')
    if type(operation_id) is not int or operation_id <= 0:
        _reject('consumption_binding_mismatch')
    operation = models.OperationLog.objects.filter(pk=operation_id).first()
    _operation_check(operation, stored, record, actor, profile)
    # No writer, normalizer, completeness refresh, save, or log on exact replay.
    return {**deepcopy(result), 'status': 'already_applied'}


def _create(profile, actor, bundle):
    payload = bundle['writer_payload']
    try:
        existing = horse_race_records.resolve_existing_race_record(profile, payload)
    except (horse_race_records.DuplicateRaceRecordError, horse_race_records.AmbiguousLegacyRaceRecordError):
        _reject('record_identity_ambiguous')
    if existing is not None:
        _reject('existing_unreviewed_record')
    before_profile, before_counts = _state(profile), _counts(profile)
    # Existing C defaults remain UNSET; parent partial totals/authority are NOT passed.
    try:
        written = horse_race_records.upsert_race_record(profile, payload)
    except (horse_race_records.DuplicateRaceRecordError, horse_race_records.AmbiguousLegacyRaceRecordError):
        _reject('record_identity_ambiguous')
    if written.action != 'created':
        _reject('writer_not_created')
    record = written.record
    record.refresh_from_db()
    profile.refresh_from_db()
    _record_readback(record, bundle)
    after_profile, after_counts = _state(profile), _counts(profile)
    if any(after_profile[key] != value for key, value in before_profile.items() if key not in PROFILE_DERIVED_FIELDS):
        _reject('writer_profile_protection')
    expected_counts = dict(before_counts, records=before_counts['records']+1,
        collected_start_count=before_counts['collected_start_count']+1,
        unlinked_race_record_count=before_counts['unlinked_race_record_count']+1)
    if (after_counts != expected_counts or any(getattr(profile, key) != after_counts[key]
            for key in ('collected_start_count', 'linked_race_event_count', 'unlinked_race_record_count'))):
        _reject('writer_count_protection')
    _freshness(bundle)
    audit = _json_safe(dict(schema_version=SOURCE_ROLE,
        prepared_binding=deepcopy(bundle['prepared']['binding']), review_input_binding=_review_binding(bundle),
        h02_idempotency_key=bundle['candidate']['idempotency_key'],
        selected_row_sha=bundle['prepared']['binding']['selected_row_sha256'],
        record_after=_record_audit_state(record), before_counts=before_counts, after_counts=after_counts,
        parent_career=deepcopy(bundle['prepared']['row_module']['coverage']['parent_career'])))
    diff = _json_safe({'record_id': {'before': None, 'after': record.pk},
                       'counts': {'before': before_counts, 'after': after_counts}})
    stored = models.HorseProfileDataCandidate.objects.create(profile=profile,
        module=models.HorseProfileModule.RACE_RECORD, source_name=SOURCE_ROLE, source_url=record.source_url,
        candidate_payload=_payload(bundle), diff_payload=diff, raw_payload=audit, confidence=0,
        status=models.HorseProfileCandidateStatus.APPLIED, applied_by=actor, applied_at=timezone.now())
    result = _result(stored, record.pk, bundle, after_counts)
    audit['h03_result'] = deepcopy(result)
    stored.raw_payload = deepcopy(audit)
    stored.save(update_fields=['raw_payload', 'updated_at'])
    operation = log_operation(action_type='horse_candidate_applied', target_type='horse_profile',
        target_id=profile.pk, detail=f'已审私有独立履历 candidate={stored.pk} record={record.pk}', admin=actor)
    _operation_check(operation, stored, record, actor, profile)
    audit['operation_id'] = operation.pk
    stored.raw_payload = deepcopy(audit)
    stored.save(update_fields=['raw_payload', 'updated_at'])
    stored.refresh_from_db()
    record.refresh_from_db()
    profile.refresh_from_db()
    _candidate_check(stored, actor, bundle, 'audit_readback_mismatch')
    _equal(stored.raw_payload, audit, 'audit_readback_mismatch')
    _equal(stored.diff_payload, diff, 'audit_readback_mismatch')
    _record_readback(record, bundle)
    _equal(_record_audit_state(record), audit['record_after'], 'audit_readback_mismatch')
    _operation_check(operation, stored, record, actor, profile)
    if _state(profile) != after_profile or _counts(profile) != after_counts:
        _reject('audit_profile_protection')
    return result


def _apply_independent_career_row_transaction(*, packet, source_raw, reviewed_raw,
        expected_source_sha256, selected_row_sha256, expected_review_sha256,
        actor_id, code_sha, permission_binding, dry_run):
    """仅私有机制。真实准入未建立；不接受prepared dict或caller grant。

    所有业务拒绝抛固定CommandError；系统/保存/序列化错误原样传播。
    外层atomic退出时统一回滚，不捕获后返回伪成功，不重试未知结果。
    """
    bundle = _prepare(packet=packet, source_raw=source_raw, reviewed_raw=reviewed_raw,
        expected_source_sha256=expected_source_sha256, selected_row_sha256=selected_row_sha256,
        expected_review_sha256=expected_review_sha256, actor_id=actor_id, code_sha=code_sha,
        permission_binding=permission_binding, dry_run=dry_run)
    _freshness(bundle)
    if connection.vendor != 'postgresql':
        _reject('postgresql_required')
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '15s'")
        actor = get_user_model().objects.select_for_update(no_key=True).filter(pk=actor_id).first()
        _staff(actor, bundle['decision'])
        _freshness(bundle)
        profile = models.HorseProfile.objects.select_for_update(of=('self',)).filter(
            pk=bundle['target']['profile_id']).first()
        _profile_gate(profile, bundle)
        _freshness(bundle)
        baseline = _utc(bundle['target']['profile_baseline'], 'profile_baseline')
        if bundle['decision']['module_reviews']['race_record']['status'] == 'ignore':
            if profile.updated_at != baseline:
                _reject('stale_baseline')
            result = dict(status='ignored', published=False, committed=False, record_id=None,
                candidate_id=None, entity_key=bundle['target']['entity_key'],
                review_input_sha256=bundle['review_sha256'], **LABELS)
        else:
            receipts = list(models.HorseProfileDataCandidate.objects.select_for_update(of=('self',)).filter(
                profile=profile, module=models.HorseProfileModule.RACE_RECORD, source_name=SOURCE_ROLE,
                raw_payload__h02_idempotency_key=bundle['candidate']['idempotency_key'],
                raw_payload__selected_row_sha=selected_row_sha256)[:2])
            if len(receipts) > 1:
                _reject('consumption_ambiguous')
            if receipts:
                result = _replay(receipts[0], profile, actor, bundle)
            else:
                if profile.updated_at != baseline:
                    _reject('stale_baseline')
                result = _create(profile, actor, bundle)
        # Locks survive these final current-state checks through commit/rollback.
        actor.refresh_from_db(fields=['is_active', 'is_staff', actor.USERNAME_FIELD])
        profile.refresh_from_db()
        _staff(actor, bundle['decision'])
        _profile_gate(profile, bundle)
        _freshness(bundle)
        if dry_run:
            result = {**result, 'status': 'dry_run', 'simulated_status': result['status'],
                      'committed': False, 'record_id': None, 'candidate_id': None}
        json.dumps(result, sort_keys=True, allow_nan=False)  # Must precede commit.
        if dry_run:
            transaction.set_rollback(True)
        return result

"""Consume one independently reviewed private HKJC career row, atomically.

Reuses the original writer and legal-link receipts; no source fetch, permission
registration, publication, or adoption of legacy records.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
import hashlib
import re

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from stable import models
from . import horse_race_records
from .horse_basic_profile_from_cache import _identity_reason, _json_safe
from .horse_career_record_link_from_cache import (
    PROFILE_DERIVED_FIELDS, RECORD_CHANGED_FIELDS, SOURCE_ROLE as LINK_ROLE,
)
from .operations import log_operation

from .horse_basic_profile_prepare_input import (
    MAX_BYTES, _bound, _equal, _reject, _strict_json, _strict_packet, _prepare, _utc,
)
from .horse_target_inventory import _sha
from .p0_horse_completion_adapters import _normalize_race_record

SOURCE_ROLE = 'h03_hkjc_career_record_review.v1'
REVIEW_SCHEMA = 'h03-career-record-reviewed-input.v1'
REVIEW_FIELDS = {'schema_version', 'code_sha', 'inputs', 'target', 'scope',
                'module_reviews', 'reviewer_id', 'before', 'after'}


def prepare_reviewed_career_record(*, packet, source_raw, reviewed_raw,
                                   expected_review_sha256, expected_row_sha256,
                                   actor, code_sha, dry_run):
    """Read the actual original bytes; rebuild real cache/H02 and row projection.

    packet is the original packet bytes, not a dict reserialized by the caller.
    This prerequisite does not itself authorize persistence or acquire actor locks.
    """
    if any(type(raw) is not bytes or len(raw) > MAX_BYTES for raw in (packet, source_raw, reviewed_raw)):
        _reject('input_bytes_or_size')
    if type(expected_row_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', expected_row_sha256):
        _reject('row_sha_invalid')
    _bound(reviewed_raw, expected_review_sha256, 'review_sha_invalid', 'review_sha_mismatch')
    decision = _strict_json(reviewed_raw)
    if type(decision) is not dict or set(decision) != REVIEW_FIELDS or decision['schema_version'] != REVIEW_SCHEMA:
        _reject('review_schema')
    if type(dry_run) is not bool or not re.fullmatch(r'[0-9a-f]{40}', str(code_sha)):
        _reject('execution_arguments')
    _equal(decision['code_sha'], code_sha, 'review_code_mismatch')
    if type(decision['reviewer_id']) is not int or decision['reviewer_id'] <= 0:
        _reject('review_actor_invalid')
    _equal(decision['reviewer_id'], getattr(actor, 'pk', None), 'review_actor_mismatch')
    inputs = decision['inputs']
    if type(inputs) is not dict or set(inputs) != {'packet', 'cache'}:
        _reject('review_inputs')
    for key, raw in (('packet', packet), ('cache', source_raw)):
        if type(inputs[key]) is not dict or set(inputs[key]) != {'path', 'sha256'}:
            _reject('review_inputs')
        _bound(raw, inputs[key]['sha256'], 'input_sha_invalid', 'input_sha_mismatch')
    checked_packet = _strict_packet(packet)
    _equal(inputs['cache']['path'], checked_packet['source_file'], 'review_source_path')
    _, plan, candidate = _prepare(checked_packet, source_raw, inputs['cache']['sha256'])
    source = _strict_json(source_raw, allow_float=True)
    matches = [item for item in source['career']['records'] if _sha(item) == expected_row_sha256]
    if len(matches) != 1:
        _reject('selected_row_missing_or_ambiguous')
    selected = matches[0]
    scope = {'module': 'race_record', 'operation': 'create_unlinked',
             'selected_row_sha': expected_row_sha256, 'event_id': None, 'result_id': None}
    _equal(decision['scope'], scope, 'review_scope_mismatch')
    target = {'profile_id': int(candidate['entity_key'].removeprefix('profile:')),
              'entity_key': candidate['entity_key'], 'entity_version': candidate['entity_version'],
              'h02_idempotency_key': candidate['idempotency_key'],
              'inventory_sha256': plan['inventory_sha256'], 'h02_plan_sha256': plan['content_sha256']}
    if not 0 < target['profile_id'] <= 10**12:
        _reject('target_pk')
    _equal(decision['target'], target, 'review_target_mismatch')
    if type(decision['module_reviews']) is not dict or set(decision['module_reviews']) != {'race_record'}:
        _reject('review_module')
    review = decision['module_reviews']['race_record']
    if type(review) is not dict or set(review) != {'status', 'reviewed_by', 'approved_at', 'decision_source_reference'}:
        _reject('review_module')
    if review['status'] not in ('approved', 'ignore') or any(type(review[k]) is not str or not review[k]
            for k in ('reviewed_by', 'approved_at', 'decision_source_reference')):
        _reject('review_module')
    _utc(review['approved_at'], 'review_time')
    _equal(decision['before'], {'record_exists': False, 'profile_baseline': checked_packet['profile_baseline']},
           'review_before_mismatch')
    for key in ('provider', 'region', 'identity_namespace', 'external_race_id', 'external_horse_id',
                'operator', 'venue_key', 'race_date', 'race_number', 'timezone'):
        if type(selected.get(key)) is not str or not selected[key].strip():
            _reject('strong_row_identity_missing')
    if (selected['provider'] != 'hkjc' or selected.get('source_name') != 'hkjc' or selected['region'] != 'hong_kong'
            or selected['identity_namespace'] != 'hkjc-race-v1' or selected['operator'] != 'hkjc'
            or selected['timezone'] != 'Asia/Hong_Kong'
            or selected['external_horse_id'] != source['source']['external_horse_id']):
        _reject('row_identity_conflict')
    if selected.get('event_id') is not None or selected.get('result_id') is not None:
        _reject('cache_binding_forbidden')
    normalized = _normalize_race_record(selected)
    inferred = _normalize_race_record({k: v for k, v in selected.items() if k != 'start_status'})
    finish_evidence = _normalize_race_record({k: v for k, v in selected.items() if k not in ('start_status', 'result_status')})
    if (normalized['start_status'] != 'started' or inferred['start_status'] != 'started'
            or finish_evidence['start_status'] != 'started' or normalized['race_date_precision'] != 'exact'):
        _reject('record_not_started_exact')
    _equal(decision['after'], normalized, 'review_after_mismatch')
    writer_payload = deepcopy(normalized)
    writer_payload.update(race_date=date.fromisoformat(normalized['race_date']),
                          race_region='hong_kong', raw_payload=deepcopy(selected), event_id=None, result_id=None)
    return {'packet': checked_packet, 'decision': decision, 'candidate': candidate, 'plan': plan,
            'selected': selected, 'normalized': normalized, 'writer_payload': writer_payload,
            'target': target, 'source_time': source['source']['fetched_at'],
            'review_sha256': hashlib.sha256(reviewed_raw).hexdigest()}


def _state(obj):
    return {field.attname: deepcopy(getattr(obj, field.attname)) for field in obj._meta.concrete_fields}


def _record_audit_state(record):
    """Serialize the model's sole Decimal field without losing audit precision."""
    state = _state(record)
    distance = state['distance_meters_normalized']
    if distance is not None:
        if type(distance) is not Decimal or not distance.is_finite():
            raise ValueError('audit_record_distance')
        state['distance_meters_normalized'] = str(distance)
    # Retain the shared strict contract for every other field and nested value.
    return _json_safe(state)


def _freshness(bundle):
    now = timezone.now()
    packet, review = bundle['packet'], bundle['decision']['module_reviews']['race_record']
    source = _utc(bundle['source_time'], 'source_time')
    as_of = _utc(packet['as_of'], 'packet_time')
    approved = _utc(review['approved_at'], 'review_time')
    if source > now or as_of > now:
        _reject('source_or_packet_future')
    if approved > now:
        _reject('review_future')
    if (now - source).total_seconds() > packet['max_age_seconds']:
        _reject('source_expired')


def _staff(actor, decision):
    if actor is None or not actor.is_active or not actor.is_staff:
        _reject('actor_not_staff')
    _equal(actor.pk, decision['reviewer_id'], 'review_actor_mismatch')
    _equal(actor.get_username(), decision['module_reviews']['race_record']['reviewed_by'], 'review_actor_mismatch')


def _profile_gate(profile, bundle):
    if profile is None:
        _reject('target_missing')
    if profile.review_status not in (models.HorseProfileStatus.DRAFT, models.HorseProfileStatus.READY) or profile.hidden_at is not None:
        _reject('target_not_private')
    reason = _identity_reason(profile, bundle['candidate']['identity_evidence'])
    if reason:
        _reject(reason)
    if profile.racing_region != 'hong_kong':
        _reject('profile_region_conflict')
    if (profile.manual_lock_flags or {}).get(models.HorseProfileModule.RACE_RECORD):
        _reject('module_locked')


def _binding(bundle):
    # Entire independently bound decision plus its original byte SHA. Candidate
    # metadata is additional provenance, not a replacement for external anchors.
    return {'reviewed_input_sha256': bundle['review_sha256'], 'decision': deepcopy(bundle['decision'])}


def _counts(profile):
    records = profile.race_records.all()
    return {'records': records.count(),
            'collected_start_count': records.filter(start_status='started').count(),
            'linked_race_event_count': records.filter(event__isnull=False).count(),
            'unlinked_race_record_count': records.filter(event__isnull=True).count()}


def _record_readback(record, bundle):
    if (record.horse_profile_id != bundle['target']['profile_id'] or record.event_id is not None
            or record.result_id is not None or record.start_status != 'started'
            or record.race_date_precision != 'exact'):
        _reject('writer_record_protection')
    if record.normalization_issues:
        _reject('writer_normalization_issue')
    _equal(record.raw_payload, bundle['selected'], 'writer_source_drift')
    if not horse_race_records.race_record_matches_upsert_payload(record, bundle['writer_payload']):
        _reject('writer_fact_conflict')
    if (record.idempotency_key != horse_race_records.record_idempotency_key(record.horse_profile, bundle['writer_payload'])
            or record.canonical_race_key != horse_race_records.canonical_race_key(record.horse_profile, bundle['writer_payload'])):
        _reject('writer_identity_conflict')


def _candidate_contract(stored, actor, bundle):
    if (stored.profile_id != bundle['target']['profile_id'] or stored.module != models.HorseProfileModule.RACE_RECORD
            or stored.source_name != SOURCE_ROLE or stored.status != models.HorseProfileCandidateStatus.APPLIED
            or stored.confidence != 0 or stored.applied_by_id != actor.pk or stored.applied_at is None):
        _reject('consumption_candidate_invalid')
    _equal(stored.candidate_payload, _json_safe({'items': [bundle['writer_payload']]}), 'consumption_payload_drift')


def _replay(stored, profile, actor, bundle):
    _candidate_contract(stored, actor, bundle)
    audit = stored.raw_payload
    if type(audit) is not dict or stored.status != models.HorseProfileCandidateStatus.APPLIED:
        _reject('consumption_not_applied')
    _equal(audit.get('review_input_binding'), _binding(bundle), 'review_binding_conflict')
    _equal(audit.get('entity_key'), bundle['target']['entity_key'], 'consumption_target_drift')
    _equal(audit.get('entity_version'), bundle['target']['entity_version'], 'consumption_target_drift')
    if stored.applied_by_id != actor.pk:
        _reject('consumption_actor_drift')
    result = audit.get('h03_result')
    if (type(result) is not dict or result.get('candidate_id') != stored.pk
            or type(result.get('record_id')) is not int or result['record_id'] <= 0
            or result.get('status') != 'applied' or result.get('published') is not False
            or result.get('committed') is not True):
        _reject('consumption_receipt_invalid')
    record = models.HorseRaceRecord.objects.select_for_update(of=('self',)).filter(
        pk=result['record_id'], horse_profile=profile).first()
    if record is None or record.result_id is not None or record.normalization_issues:
        _reject('consumption_record_invalid')
    _equal(record.raw_payload, bundle['selected'], 'record_source_drift')
    if _sha(record.raw_payload) != bundle['decision']['scope']['selected_row_sha']:
        _reject('record_source_drift')
    original = audit.get('record_after')
    if type(original) is not dict or original.get('id') != record.pk or original.get('event_id') is not None:
        _reject('consumption_receipt_invalid')
    allowed = set()
    if record.event_id is not None:
        linked = list(models.HorseProfileDataCandidate.objects.filter(
            profile=profile, module=models.HorseProfileModule.RACE_RECORD, source_name=LINK_ROLE,
            status=models.HorseProfileCandidateStatus.APPLIED,
            raw_payload__h02_idempotency_key=bundle['candidate']['idempotency_key'],
            raw_payload__selected_row_sha=bundle['decision']['scope']['selected_row_sha'],
            raw_payload__h03_result__record_id=record.pk)[:2])
        if len(linked) != 1:
            _reject('legal_link_receipt_missing')
        link = linked[0]
        receipt = link.raw_payload.get('h03_result')
        if (type(receipt) is not dict or receipt.get('candidate_id') != link.pk
                or receipt.get('link_diff', {}).get('event_id', {}).get('after') != record.event_id
                or receipt.get('published') is not False):
            _reject('legal_link_receipt_invalid')
        expected_key = horse_race_records.canonical_race_key(profile, dict(bundle['writer_payload'], event_id=record.event_id))
        if record.canonical_race_key != expected_key:
            _reject('legal_link_record_drift')
        allowed = RECORD_CHANGED_FIELDS
    current = _record_audit_state(record)
    if current.keys() != original.keys() or any(current[k] != original[k] for k in current.keys() - allowed):
        _reject('record_fact_conflict')
    # Never invoke the writer/normalizer/completeness refresh on a receipt replay.
    return {**deepcopy(result), 'status': 'already_applied', 'derived_counts': _counts(profile)}


def _apply(bundle, actor_pk, dry_run):
    if connection.vendor != 'postgresql':
        _reject('postgresql_required')
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '15s'")
        # Non-key User locking serializes real revocation while retaining FK
        # KEY SHARE compatibility for the existing candidate/operation log.
        actor = get_user_model().objects.select_for_update(no_key=True).filter(pk=actor_pk).first()
        _staff(actor, bundle['decision'])
        _freshness(bundle)  # Actor lock waits cannot extend validity.
        profile = models.HorseProfile.objects.select_for_update(of=('self',)).filter(pk=bundle['target']['profile_id']).first()
        _profile_gate(profile, bundle)
        _freshness(bundle)
        baseline = _utc(bundle['packet']['profile_baseline'], 'profile_baseline')
        if bundle['decision']['module_reviews']['race_record']['status'] == 'ignore':
            if profile.updated_at != baseline:
                _reject('stale_baseline')
            result = {'status': 'ignored', 'published': False, 'committed': False,
                      'candidate_id': None, 'record_id': None, 'entity_key': bundle['target']['entity_key']}
        else:
            consumed = list(models.HorseProfileDataCandidate.objects.select_for_update(of=('self',)).filter(
                profile=profile, module=models.HorseProfileModule.RACE_RECORD, source_name=SOURCE_ROLE,
                raw_payload__h02_idempotency_key=bundle['candidate']['idempotency_key'],
                raw_payload__selected_row_sha=bundle['decision']['scope']['selected_row_sha'])[:2])
            if len(consumed) > 1:
                _reject('consumption_ambiguous')
            if consumed:
                result = _replay(consumed[0], profile, actor, bundle)
            else:
                if profile.updated_at != baseline:
                    _reject('stale_baseline')
                try:
                    existing = horse_race_records.resolve_existing_race_record(profile, bundle['writer_payload'])
                except (horse_race_records.DuplicateRaceRecordError, horse_race_records.AmbiguousLegacyRaceRecordError):
                    _reject('record_identity_ambiguous')
                if existing is not None:
                    _reject('existing_unreviewed_record')
                before_profile, before_counts = _state(profile), _counts(profile)
                try:
                    written = horse_race_records.upsert_race_record(profile, bundle['writer_payload'])
                except (horse_race_records.DuplicateRaceRecordError, horse_race_records.AmbiguousLegacyRaceRecordError):
                    _reject('record_identity_ambiguous')
                if written.action != 'created':
                    _reject('writer_not_created')
                record = written.record
                record.refresh_from_db()
                profile.refresh_from_db()
                _record_readback(record, bundle)
                after_profile, after_counts = _state(profile), _counts(profile)
                if any(after_profile[k] != v for k, v in before_profile.items() if k not in PROFILE_DERIVED_FIELDS):
                    _reject('writer_profile_protection')
                expected_counts = dict(before_counts, records=before_counts['records'] + 1,
                    collected_start_count=before_counts['collected_start_count'] + 1,
                    unlinked_race_record_count=before_counts['unlinked_race_record_count'] + 1)
                if after_counts != expected_counts or any(getattr(profile, k) != after_counts[k]
                        for k in ('collected_start_count', 'linked_race_event_count', 'unlinked_race_record_count')):
                    _reject('writer_count_protection')
                _freshness(bundle)
                audit = {'schema_version': SOURCE_ROLE, 'review_input_binding': _binding(bundle),
                    'h02_idempotency_key': bundle['candidate']['idempotency_key'],
                    'selected_row_sha': bundle['decision']['scope']['selected_row_sha'],
                    **deepcopy(bundle['target']), 'source_time': bundle['source_time'],
                    'source_sha256': bundle['decision']['inputs']['cache']['sha256'],
                    'record_after': _record_audit_state(record), 'before_counts': before_counts,
                    'after_counts': after_counts, 'profile_baseline': baseline.isoformat()}
                stored = models.HorseProfileDataCandidate.objects.create(
                    profile=profile, module=models.HorseProfileModule.RACE_RECORD, source_name=SOURCE_ROLE,
                    source_url=record.source_url, candidate_payload=_json_safe({'items': [bundle['writer_payload']]}),
                    diff_payload=_json_safe({'record_id': {'before': None, 'after': record.pk},
                                            'counts': {'before': before_counts, 'after': after_counts}}),
                    raw_payload=_json_safe(audit), confidence=0, status=models.HorseProfileCandidateStatus.APPLIED,
                    applied_by=actor, applied_at=timezone.now())
                result = {'status': 'applied', 'published': False, 'committed': True,
                    'candidate_id': stored.pk, 'record_id': record.pk, 'entity_key': bundle['target']['entity_key'],
                    'review_input_sha256': bundle['review_sha256'], 'derived_counts': after_counts}
                stored.raw_payload['h03_result'] = deepcopy(result)
                stored.save(update_fields=['raw_payload', 'updated_at'])
                operation = log_operation(action_type='horse_candidate_applied', target_type='horse_profile', target_id=profile.pk,
                    detail=f'已审私有单行赛绩 candidate={stored.pk} record={record.pk}', admin=actor)
                # Actual persistent receipt and record must agree, not just the
                # returned writer/candidate objects (including swallowed issues).
                stored.refresh_from_db()
                record.refresh_from_db()
                profile.refresh_from_db()
                _candidate_contract(stored, actor, bundle)
                operation.refresh_from_db()
                if (operation.action_type != 'horse_candidate_applied' or operation.target_type != 'horse_profile'
                        or operation.target_id != str(profile.pk) or operation.admin_id != actor.pk):
                    _reject('operation_readback_mismatch')
                _equal(stored.raw_payload.get('h03_result'), result, 'audit_readback_mismatch')
                _equal(stored.raw_payload.get('review_input_binding'), _binding(bundle), 'audit_binding_mismatch')
                _record_readback(record, bundle)
                if _state(profile) != after_profile or _counts(profile) != after_counts:
                    _reject('audit_profile_protection')
        actor.refresh_from_db(fields=['is_active', 'is_staff', actor.USERNAME_FIELD])
        _staff(actor, bundle['decision'])  # Actor lock held through commit/rollback.
        _profile_gate(profile, bundle)
        _freshness(bundle)
        if dry_run:
            result = {**result, 'status': 'dry_run', 'simulated_status': result['status'], 'committed': False,
                      'record_id': None, 'candidate_id': None}
        json.dumps(result, sort_keys=True, allow_nan=False)  # Failure must precede commit.
        if dry_run:
            transaction.set_rollback(True)
        return result


def consume_reviewed_career_record(*, packet, source_raw, reviewed_raw,
                                   expected_review_sha256, expected_row_sha256,
                                   actor, code_sha, dry_run):
    bundle = prepare_reviewed_career_record(
        packet=packet, source_raw=source_raw, reviewed_raw=reviewed_raw,
        expected_review_sha256=expected_review_sha256, expected_row_sha256=expected_row_sha256,
        actor=actor, code_sha=code_sha, dry_run=dry_run)
    if not isinstance(actor, get_user_model()) or actor.pk is None:
        _reject('local_actor_required')
    # Source time was reconstructed from the captured, bound bytes.
    _freshness(bundle)
    try:
        return _apply(bundle, actor.pk, dry_run)
    except CommandError as exc:
        return {'status': 'blocked', 'reason': str(exc), 'published': False, 'committed': False}
    except DatabaseError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) == '55P03' or getattr(exc.__cause__, 'pgcode', None) == '55P03':
            return {'status': 'blocked', 'reason': 'resource_busy', 'published': False, 'committed': False}
        raise

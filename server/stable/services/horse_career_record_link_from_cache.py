"""H03 单条已有赛绩离线补连；只复用既有身份/binding 和 canonical writer。

没有抓取、登记、换绑、权限标记或公开行为。profile 锁只串行化本入口；
旧 writer 的全局并发安全不在此合同中。缺真实既有合同时保持 blocked。
"""
from copy import deepcopy
from datetime import date
import json
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from stable import models
from . import horse_race_records, race_data_source_adapters
from .horse_basic_profile_from_cache import _baseline, _identity_reason, _json_safe
from .horse_cache_reuse import plan_cache_reuse
from .horse_source_cache_reuse_adapter import adapt_hkjc_source_cache
from .horse_target_inventory import _plain, _sha
from .operations import log_operation
from .p0_horse_completion_adapters import _normalize_race_record
from .race_data_sync_admission import binding_admission_reason

SOURCE_ROLE = 'h03_hkjc_career_link_cache.v1'
# Complete projection for _race_record_values, including all optional writes.
WRITER_FIELDS = (
    'race_name', 'race_year', 'race_date', 'race_date_precision', 'race_name_normalized',
    'race_region', 'race_number', 'grade_text', 'normalized_grade', 'racecourse',
    'distance_text', 'distance_meters', 'surface', 'race_type_text', 'horse_number',
    'barrier', 'jockey_name', 'carried_weight', 'finish_time', 'prize_text',
    'finish_position', 'result_status', 'start_status', 'is_overseas', 'is_major_win',
    'source_name', 'source_url', 'raw_payload', 'event_id', 'result_id', 'major_win_order',
)
PROFILE_DERIVED_FIELDS = {
    'updated_at', 'career_history_status', 'collected_start_count', 'linked_race_event_count',
    'unlinked_race_record_count', 'overseas_start_count', 'deduplicated_source_record_count',
    'career_history_gap_count', 'career_history_gap_reasons',
}
RECORD_CHANGED_FIELDS = {
    'event_id', 'canonical_race_key', 'updated_at', 'normalized_at',
    'normalization_input_sha256', 'normalization_version', 'normalization_issues',
}


class _Rejected(Exception):
    """Only fixed local reason codes cross this boundary; outer atomic rolls back."""


def _blocked(reason):
    return {'status': 'blocked', 'reason': reason, 'published': False}


def _require(condition, reason):
    if not condition:
        raise _Rejected(reason)


def _pk(value):
    if type(value) is not int or not 0 < value <= 10**12:
        raise ValueError('target_pk')
    return value


def _digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('input_digest')
    return value


def _state(obj):
    return {field.attname: deepcopy(getattr(obj, field.attname)) for field in obj._meta.concrete_fields}


def _locked(model, pk):
    obj = model.objects.select_for_update(nowait=True, of=('self',)).filter(pk=pk).first()
    _require(obj is not None, 'target_missing')
    return obj


def _contract(*, event, enrollment, source, binding, selected, expected_sha, expected_policy=None):
    """Use the live server clock only; callers cannot backdate source admission."""
    now = timezone.now()
    try:
        policy = race_data_source_adapters.load_multisource_policy(now=now)
        route = policy.route_for({'provider': source.source_key, 'region': source.region_code,
                                  'identity_namespace': source.identity_namespace})
        _require(route is not None, 'binding_route_missing')
        _require(expected_policy is None or policy.digest == expected_policy, 'policy_changed')
        _require(enrollment.event_id == event.pk and enrollment.authority_version == 2
                 and enrollment.state == 'enrolled' and enrollment.retired_at is None, 'enrollment_invalid')
        _require(binding.enrollment_id == enrollment.pk and binding.source_identity_id == source.pk
                 and source.event_id == event.pk and binding.registry_schema_version == 3
                 and binding.binding_manifest_sha256 == expected_sha, 'binding_target_drift')
        # Populate FK caches with the objects locked by this transaction, never
        # the discovery query or an unlocked select_related snapshot.
        binding.enrollment = enrollment
        binding.source_identity = source
        source.event = event
        reason = binding_admission_reason(binding=binding, route=route, now=now,
                                          capability='racecard', check_runtime=False)
        _require(not reason, 'binding_contract_invalid')
        evidence = source.identity_fields.get('multisource_v2')
        _require(type(evidence) is dict, 'strong_event_identity_missing')
        _require(source.source_key == selected['provider'] == 'hkjc'
                 and source.region_code == selected['region'] == 'hong_kong'
                 and source.identity_namespace == selected['identity_namespace'] == route.identity_namespace
                 and source.external_race_id == selected['external_race_id'], 'event_identity_conflict')
        for key in ('operator', 'venue_key', 'local_date', 'race_number', 'timezone'):
            incoming = selected['race_date'] if key == 'local_date' else selected[key]
            _require(evidence.get(key) == incoming and bool(incoming), 'event_anchor_conflict')
        _require(route.operator == selected['operator'] and route.timezone == selected['timezone'], 'route_anchor_conflict')
        _require(event.local_date is not None and str(event.local_date) == selected['race_date']
                 and event.year == event.edition_year == event.local_date.year
                 and event.country_region == route.country_region, 'event_date_edition_conflict')
        # Existing helper also checks the event timezone and reviewed venue aliases.
        return policy.digest
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        raise _Rejected('binding_contract_unavailable') from None


def _record_contract(record, profile, selected, normalized, event_pk, row_sha):
    _require(record.horse_profile_id == profile.pk and record.source_name == 'hkjc', 'record_ownership')
    _require(record.event_id in (None, event_pk) and record.result_id is None, 'record_already_bound')
    _require(type(record.raw_payload) is dict and _sha(record.raw_payload) == row_sha, 'record_source_drift')
    _require(not record.normalization_issues, 'record_normalization_issue')
    for field in (set(WRITER_FIELDS) & normalized.keys()) - {'event_id', 'result_id', 'raw_payload'}:
        _require(getattr(record, field) == normalized[field], 'record_fact_conflict')
    if 'eligibility_text' in selected:
        _require(record.eligibility_text == selected['eligibility_text'], 'record_fact_conflict')
    _require(record.start_status == 'started' and record.race_date_precision == 'exact', 'record_not_started_exact')
    _require(record.raw_payload.get('external_race_id') == selected['external_race_id'], 'record_race_identity')


def apply_career_record_link_from_cache(
    *, snapshot, candidate, raw_bytes, expected_sha256, ref, source_ref,
    entity_versions, as_of, max_age_seconds, expected_updated_at, actor,
    selected_row_sha, record_pk, source_identity_pk, event_pk, binding_pk,
    expected_binding_manifest_sha256, expected_record_updated_at,
):
    """Validate → profile/child locks → safety → replay → baseline → writer/audit.

    Input/security/busy failures return blocked. Persistence/writer/log errors
    propagate after rollback; no retry, source fallback or permission mutation.
    """
    try:
        _plain(candidate)
        cache = adapt_hkjc_source_cache(raw_bytes, expected_sha256=expected_sha256, ref=ref, source_ref=source_ref)
        plan = plan_cache_reuse(snapshot, [cache], entity_versions, as_of=as_of, max_age_seconds=max_age_seconds)
        matches = [item for item in plan['candidates'] if item['entity_key'] == candidate.get('entity_key')]
        if len(matches) != 1 or _sha(matches[0]) != _sha(candidate):
            return _blocked('candidate_mismatch')
        checked = matches[0]
        if checked['action'] != 'reusable' or checked['cache_refs'] != [ref]:
            return _blocked('cache_not_reusable')
        entity_key = checked['entity_key']
        if not entity_key.startswith('profile:'):
            return _blocked('existing_profile_required')
        profile_pk = _pk(int(entity_key.removeprefix('profile:')))
        if entity_key != f'profile:{profile_pk}':
            return _blocked('profile_key')
        for value in (record_pk, source_identity_pk, event_pk, binding_pk):
            _pk(value)
        _digest(selected_row_sha)
        _digest(expected_binding_manifest_sha256)
        profile_baseline, record_baseline = _baseline(expected_updated_at), _baseline(expected_record_updated_at)
        if not isinstance(actor, get_user_model()) or actor.pk is None:
            return _blocked('local_actor_required')
        source_cache = json.loads(cache['content'])
        rows = [item for item in source_cache['career']['records'] if _sha(item) == selected_row_sha]
        if len(rows) != 1:
            return _blocked('selected_row_missing_or_ambiguous')
        selected = rows[0]
        _plain(selected)
        for key in ('provider', 'region', 'identity_namespace', 'external_race_id', 'external_horse_id',
                    'operator', 'venue_key', 'race_date', 'race_number', 'timezone'):
            if type(selected.get(key)) is not str or not selected[key].strip():
                return _blocked('strong_event_identity_missing')
        if selected.get('event_id') or selected.get('result_id'):
            return _blocked('cache_binding_forbidden')
        if selected['external_horse_id'] != source_cache['source']['external_horse_id']:
            return _blocked('horse_identity_conflict')
        normalized = _normalize_race_record(selected)
        if normalized['start_status'] != 'started' or normalized['race_date_precision'] != 'exact':
            return _blocked('record_not_started_exact')
        # The existing cache normalizer emits an ISO date string; the model
        # and canonical writer use a typed date. Keep raw fingerprint intact.
        normalized['race_date'] = date.fromisoformat(normalized['race_date'])
        input_sha = _sha({'candidate': checked, 'snapshot_sha': _sha(snapshot), 'entity_versions': entity_versions,
                         'as_of': as_of, 'max_age_seconds': max_age_seconds, 'source_role': SOURCE_ROLE,
                         'profile_baseline': profile_baseline.isoformat(), 'record_baseline': record_baseline.isoformat(),
                         'selected_row_sha': selected_row_sha, 'record_pk': record_pk, 'event_pk': event_pk,
                         'source_identity_pk': source_identity_pk, 'binding_pk': binding_pk,
                         'binding_manifest_sha256': expected_binding_manifest_sha256})
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError, RecursionError):
        return _blocked('input_invalid')

    try:
        with transaction.atomic():
            profile = models.HorseProfile.objects.select_for_update(of=('self',)).filter(pk=profile_pk).first()
            _require(profile is not None, 'target_missing')
            _require(profile.review_status in (models.HorseProfileStatus.DRAFT, models.HorseProfileStatus.READY)
                     and profile.hidden_at is None, 'target_not_private')
            reason = _identity_reason(profile, checked['identity_evidence'])
            _require(not reason, reason or 'identity_invalid')
            _require(not (profile.manual_lock_flags or {}).get(models.HorseProfileModule.RACE_RECORD), 'module_locked')
            record = _locked(models.HorseRaceRecord, record_pk)
            event = _locked(models.RaceEvent, event_pk)
            # Discovery supplies only the PK; all semantic checks use locked rows.
            discovery = models.RaceDataSyncSourceBinding.objects.filter(pk=binding_pk).values('enrollment_id').first()
            _require(discovery is not None, 'binding_missing')
            enrollment = _locked(models.RaceDataSyncEnrollment, discovery['enrollment_id'])
            source = _locked(models.RaceResultSourceIdentity, source_identity_pk)
            binding = _locked(models.RaceDataSyncSourceBinding, binding_pk)
            policy_digest = _contract(event=event, enrollment=enrollment, source=source, binding=binding,
                                      selected=selected, expected_sha=expected_binding_manifest_sha256)
            _record_contract(record, profile, selected, normalized, event_pk, selected_row_sha)
            consumed = list(models.HorseProfileDataCandidate.objects.filter(
                profile=profile, module=models.HorseProfileModule.RACE_RECORD, source_name=SOURCE_ROLE,
                raw_payload__h02_idempotency_key=checked['idempotency_key'])[:2])
            _require(len(consumed) <= 1, 'consumption_ambiguous')
            if consumed:
                stored = consumed[0]
                _require(stored.raw_payload.get('input_sha256') == input_sha, 'version_content_conflict')
                _require(stored.status == models.HorseProfileCandidateStatus.APPLIED, 'consumption_not_applied')
                result = stored.raw_payload.get('h03_result')
                _require(type(result) is dict and result.get('candidate_id') == stored.pk
                         and result.get('record_id') == record.pk and record.event_id == event.pk, 'consumption_receipt_invalid')
                return {**deepcopy(result), 'status': 'already_applied'}
            _require(profile.updated_at == profile_baseline and record.updated_at == record_baseline, 'stale_baseline')
            before_record, before_profile = _state(record), _state(profile)
            before_count = profile.race_records.count()
            payload = {field: deepcopy(getattr(record, field)) for field in WRITER_FIELDS}
            payload['event_id'] = event.pk
            if record.event_id is None:
                try:
                    upsert = horse_race_records.upsert_race_record(profile, payload, record=record)
                except (horse_race_records.DuplicateRaceRecordError, horse_race_records.AmbiguousLegacyRaceRecordError):
                    raise _Rejected('record_identity_ambiguous') from None
                _require(upsert.record.pk == record.pk and not upsert.record.normalization_issues, 'writer_normalization_issue')
                record.refresh_from_db()
                profile.refresh_from_db()
                _require(not record.normalization_issues and record.event_id == event.pk and record.result_id is None
                         and profile.race_records.count() == before_count, 'writer_postcondition')
                after_record, after_profile = _state(record), _state(profile)
                _require(all(after_record[key] == value for key, value in before_record.items()
                             if key not in RECORD_CHANGED_FIELDS), 'writer_record_protection')
                _require(all(after_profile[key] == value for key, value in before_profile.items()
                             if key not in PROFILE_DERIVED_FIELDS), 'writer_profile_protection')
            # Recheck live policy/expiry after real writes, before consuming/auditing.
            _contract(event=event, enrollment=enrollment, source=source, binding=binding, selected=selected,
                      expected_sha=expected_binding_manifest_sha256, expected_policy=policy_digest)
            diff = {'event_id': {'before': before_record['event_id'], 'after': event.pk}}
            audit = {'schema_version': SOURCE_ROLE, 'h02_idempotency_key': checked['idempotency_key'],
                     'input_sha256': input_sha, 'entity_key': entity_key, 'entity_version': checked['entity_version'],
                     'content_sha256': cache['content_sha256'], 'source_time': cache['source_time'],
                     'cache_ref': ref, 'source_ref': source_ref, 'identity_evidence': checked['identity_evidence'],
                     'inventory_sha256': plan['inventory_sha256'], 'h02_plan_sha256': plan['content_sha256'],
                     'selected_row_sha': selected_row_sha, 'binding_pk': binding.pk,
                     'binding_manifest_sha256': binding.binding_manifest_sha256, 'policy_digest': policy_digest,
                     'profile_baseline': profile_baseline.isoformat(), 'record_baseline': record_baseline.isoformat()}
            stored = models.HorseProfileDataCandidate.objects.create(
                profile=profile, module=models.HorseProfileModule.RACE_RECORD, source_name=SOURCE_ROLE,
                source_url=record.source_url, candidate_payload=_json_safe({'items': [payload]}),
                diff_payload=_json_safe(diff), raw_payload=_json_safe(audit), confidence=0,
                status=models.HorseProfileCandidateStatus.APPLIED, applied_by=actor, applied_at=timezone.now())
            result = {'status': 'applied', 'published': False, 'candidate_id': stored.pk,
                      'record_id': record.pk, 'input_sha256': input_sha, 'link_diff': diff,
                      'derived_counts': {field: getattr(profile, field) for field in
                                         ('collected_start_count', 'linked_race_event_count', 'unlinked_race_record_count')}}
            stored.raw_payload['h03_result'] = _json_safe(result)
            stored.save(update_fields=['raw_payload', 'updated_at'])
            log_operation(action_type='horse_candidate_applied', target_type='horse_profile', target_id=profile.pk,
                          detail=f'本地缓存赛绩补连 candidate={stored.pk} record={record.pk} event={event.pk}', admin=actor)
            return result
    except _Rejected as exc:
        return _blocked(str(exc))
    except DatabaseError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) == '55P03' or getattr(exc.__cause__, 'pgcode', None) == '55P03':
            return _blocked('resource_busy')
        raise

#!/usr/bin/env python3
"""本轮赛事冻结包回填：默认 dry-run，每场事务，只写赛果、确认状态和审计。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from stable import models as m
from stable.services.race_result_recovery_projection import _advisory_lock_event_ids

RESULT_FIELDS = tuple(f.name for f in m.RaceEventResult._meta.concrete_fields
                      if f.name not in {'id', 'event', 'created_at', 'updated_at'})
NONFINISH = {'scratched', 'withdrawn', 'non_runner', 'disqualified', 'did_not_finish',
             'pulled_up', 'unseated_rider', 'fell', 'refused'}
PROVIDERS = {
    'jra': ('official', {'www.jra.go.jp'}),
    'nar': ('official', {'www.keiba.go.jp', 'www2.keiba.go.jp'}),
    'sporting_life': ('human_reviewed_reference', {'www.sportinglife.com', 'sportinglife.com'}),
    'zeturf': ('human_reviewed_reference', {'www.zeturf.com', 'zeturf.com', 'www.zeturf.fr'}),
}
ACTION = 'reviewed_gap_backfill'
RETIRED_SHADOW_IDS = frozenset(range(948, 954))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def bytes_sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return bytes_sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), default=str).encode())


def result_default(field):
    return copy.deepcopy(m.RaceEventResult._meta.get_field(field).get_default())


def snapshot(event_id):
    result = {'event': m.RaceEvent.objects.values().get(pk=event_id)}
    for key, model in [('runners', m.RaceEventRunner), ('control', m.RaceEventProjectionControl),
                       ('enrollment', m.RaceDataSyncEnrollment), ('lifecycle', m.RaceEventLifecycleControl),
                       ('tracking', m.RaceEventLiveTracking), ('field_authorities', m.RaceEventFieldAuthority)]:
        result[key] = list(model.objects.filter(event_id=event_id).order_by('id').values())
    result['results'] = list(m.RaceEventResult.objects.filter(event_id=event_id)
                             .order_by('finish_position', 'id').values())
    result['canonical_links'] = list(m.RaceEventProductCanonicalLink.objects.filter(
        duplicate_event_id=event_id, is_active=True).order_by('id').values())
    if event_id in RETIRED_SHADOW_IDS:
        result['memberships'] = list(m.RaceEventLifecycleEnforceMembership.objects.filter(
            event_id=event_id).order_by('id').values())
        result['registries'] = list(m.RaceEventLifecycleEnforceRegistry.objects.filter(
            pk__in=[v['registry_id'] for v in result['memberships']]).order_by('id').values())
    return result


def identity(row):
    return (row['horse_name'], row['horse_number'])


def guard(state):
    require(not state['enrollment'] and not state['tracking'], 'managed_event')
    if state['lifecycle']:
        require(state['event']['id'] in RETIRED_SHADOW_IDS and len(state['lifecycle']) == 1, 'managed_event')
        control = state['lifecycle'][0]
        require(control['mode'] == 'shadow' and control['next_refresh_at'] is None and
                not control['claim_token'] and control['claim_expires_at'] is None and
                not control['manual_pause_reason'] and
                not any(control['manifest_data'].get(k) for k in ('enforce_registry', 'race_data_sync')),
                'retired_control_not_quiescent')
        require(state.get('memberships') and state.get('registries') and
                all(v['state'] == 'retired' for v in state['memberships']) and
                all(v['state'] == 'retired' and not v['is_active'] for v in state['registries']),
                'registry_not_retired')
    require(all(c['write_owner'] == 'unmanaged' for c in state['control']), 'managed_owner')
    require(not state['canonical_links'], 'canonical_duplicate')
    event = state['event']
    require(not any((event['manual_lock_flags'] or {}).values()), 'event_manual_lock')
    require(not any(f['manual_lock'] for f in state['field_authorities']), 'field_manual_lock')
    require(event['visibility_status'] == 'published' and
            event['status'] in {'scheduled', 'running', 'finished'}, 'event_not_publishable')
    require(str(event['local_date']) < timezone.localdate().isoformat(), 'not_historical')


def validate_entry(entry, root):
    before = entry['before']
    require(digest(before) == entry['before_sha256'], 'frozen_baseline_digest')
    guard(before)
    event, source = before['event'], entry['source']
    require(entry['event_id'] == event['id'] == source['event_id'], 'source_event_mismatch')
    require(str(event['local_date']) == source['local_date'] and
            event['racecourse'] == source['racecourse'] and bool(source['title']), 'source_identity_mismatch')
    provider = PROVIDERS.get(source['provider'])
    require(provider is not None and source['authority'] == provider[0], 'source_authority_invalid')
    url = urlsplit(source['url'])
    require(url.scheme == 'https' and url.hostname in provider[1] and not url.username and
            not url.password and url.port in {None, 443}, 'source_url_invalid')
    path = root / source['path']
    require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'evidence_path_invalid')
    require(bytes_sha(path.read_bytes()) == source['sha256'], 'source_cache_drift')
    confirmed = parse_datetime(entry['confirmed_at'])
    require(confirmed is not None and timezone.is_aware(confirmed) and
            confirmed <= timezone.now(), 'confirmation_time_invalid')
    rows, evidence_rows = entry['results'], source['rows']
    require(0 < len(rows) <= 60 and len(rows) == len(evidence_rows), 'incomplete_roster')
    require([r['finish_position'] for r in rows] == list(range(1, len(rows)+1)), 'internal_order_invalid')
    require(len({identity(r) for r in rows}) == len(rows), 'duplicate_horse_identity')
    require(len({identity(r) for r in evidence_rows}) == len(rows), 'duplicate_source_identity')
    source_by_identity = {identity(r): r for r in evidence_rows}
    old_by_id = {r['id']: r for r in before['results']}
    old_ids = [r['id'] for r in rows if r['id'] is not None]
    require(len(old_ids) == len(set(old_ids)) and set(old_ids) == set(old_by_id), 'old_roster_mismatch')
    for row in rows:
        require(set(row) == set(RESULT_FIELDS) | {'id'}, 'result_field_set_invalid')
        require(isinstance(row['horse_name'], str) and row['horse_name'].strip() and
                isinstance(row['horse_number'], str), 'horse_identity_invalid')
        if row['id'] is not None:
            require(identity(row) == identity(old_by_id[row['id']]), 'old_horse_identity_drift')
        raw = source_by_identity.get(identity(row))
        require(raw is not None, 'horse_missing_from_source')
        for field in ('reported_finish_position', 'running_status'):
            require(row[field] == raw[field], 'source_result_drift')
        rank, status = row['reported_finish_position'], row['running_status']
        if status in NONFINISH:
            require(rank is None, 'nonfinish_has_rank')
        else:
            require(status in {'finished', 'dead_heat'} and type(rank) is int and
                    1 <= rank <= len(rows), 'finish_rank_invalid')
        expected_official = rank if source['authority'] == 'official' else None
        require(row['official_finish_position'] == expected_official and row['is_confirmed'] is True,
                'confirmation_authority_invalid')
        refs = row['source_refs']
        require(isinstance(refs, dict), 'result_provenance_invalid')
        for key, expected in [('official_finish_position', expected_official),
                              ('reported_finish_position', rank),
                              ('approval_authority', source['authority']),
                              ('public_label', '官方赛果' if source['authority'] == 'official' else '已人工审核赛果')]:
            require(key not in refs or refs[key] == expected, 'stale_result_semantics')
        for field in RESULT_FIELDS:
            m.RaceEventResult._meta.get_field(field).clean(row[field], None)
    ranked = [r['reported_finish_position'] for r in rows if r['reported_finish_position'] is not None]
    require(ranked and ranked[0] == 1 and ranked == sorted(ranked), 'winner_or_order_missing')
    offset = 0
    for rank in sorted(set(ranked)):
        require(rank == offset + 1, 'competition_rank_invalid')
        offset += ranked.count(rank)
    return confirmed


def protected(state):
    state = copy.deepcopy(state)
    state.pop('results')
    for key in ('status', 'result_confirmed_at', 'updated_at'):
        state['event'].pop(key)
    return state


def check_after(state, entry):
    rows = state['results']
    require(len(rows) == len(entry['results']), 'after_row_count')
    for actual, expected in zip(rows, entry['results']):
        require(all(actual[f] == expected[f] for f in RESULT_FIELDS), 'after_result_drift')
        require(expected['id'] is None or actual['id'] == expected['id'], 'after_row_id_drift')
    require(state['event']['status'] == 'finished' and
            parse_datetime(str(state['event']['result_confirmed_at'])) == parse_datetime(entry['confirmed_at']),
            'after_event_drift')
    require(digest(protected(state)) == digest(protected(entry['before'])), 'protected_field_drift')


def execute(path, expected_sha, *, apply=False, fault_hook=None):
    path = Path(path)
    data = path.read_bytes()
    require(bytes_sha(data) == expected_sha, 'manifest_sha_mismatch')
    manifest = json.loads(data)
    require(manifest['schema_version'] == 1 and bool(manifest['reviewer']), 'manifest_invalid')
    ids = [entry['event_id'] for entry in manifest['events']]
    require(ids and len(ids) == len(set(ids)), 'scope_invalid')
    reports = []
    for entry in manifest['events']:
        event_id = entry['event_id']
        try:
            confirmed = validate_entry(entry, path.parent)
            with transaction.atomic():
                if event_id in RETIRED_SHADOW_IDS:
                    from stable.services.race_event_lifecycle_enforce import acquire_registry_shared_advisory_lock
                    acquire_registry_shared_advisory_lock()
                _advisory_lock_event_ids([event_id])
                list(m.RaceEventLifecycleControl.objects.select_for_update().filter(event_id=event_id))
                event = m.RaceEvent.objects.select_for_update().get(pk=event_id)
                for model in (m.RaceEventProjectionControl, m.RaceDataSyncEnrollment,
                              m.RaceEventLiveTracking, m.RaceEventFieldAuthority,
                              m.RaceEventResult, m.RaceEventRunner):
                    list(model.objects.select_for_update().filter(event_id=event_id))
                current = snapshot(event_id)
                guard(current)
                log = m.OperationLog.objects.filter(action_type=ACTION, target_type='RaceEvent',
                    target_id=str(event_id), detail__contains=expected_sha).order_by('-id').first()
                if log:
                    receipt = json.loads(log.detail)
                    require(receipt['manifest_sha256'] == expected_sha, 'audit_manifest_mismatch')
                    check_after(current, entry)
                    require(digest(current) == receipt['after_sha256'], 'applied_snapshot_drift')
                    reports.append(dict(event_id=event_id, status='already_applied', audit_id=log.pk))
                    continue
                require(digest(current) == entry['before_sha256'], 'database_baseline_drift')
                if not apply:
                    reports.append(dict(event_id=event_id, status='dry_run', rows=len(entry['results'])))
                    continue
                # 原位交换前临时移开唯一行序号，任何异常都会事务回滚。
                temporary_start = max([r['finish_position'] for r in current['results']] + [60]) + 1
                require(temporary_start + len(current['results']) < 32767, 'temporary_order_overflow')
                for index, row in enumerate(current['results'], temporary_start):
                    m.RaceEventResult.objects.filter(pk=row['id']).update(finish_position=index)
                for row in entry['results']:
                    fields = {f: row[f] for f in RESULT_FIELDS}
                    if row['id'] is None:
                        m.RaceEventResult.objects.create(event=event, **fields)
                    else:
                        m.RaceEventResult.objects.filter(pk=row['id'], event=event).update(**fields)
                if fault_hook:
                    fault_hook(event_id=event_id, stage='after_results')
                event.status = 'finished'
                event.result_confirmed_at = confirmed
                event.save(update_fields=['status', 'result_confirmed_at', 'updated_at'])
                after = snapshot(event_id)
                check_after(after, entry)
                log = m.OperationLog.objects.create(action_type=ACTION, target_type='RaceEvent',
                    target_id=str(event_id), detail=json.dumps(dict(manifest_sha256=expected_sha,
                    before_sha256=entry['before_sha256'], after_sha256=digest(after),
                    reviewer=manifest['reviewer'], source_url=entry['source']['url'],
                    source_sha256=entry['source']['sha256'], authority=entry['source']['authority']),
                    ensure_ascii=False, sort_keys=True))
            reports.append(dict(event_id=event_id, status='applied', rows=len(entry['results']), audit_id=log.pk))
        except Exception as exc:
            reason = str(exc) if type(exc) is ValueError else type(exc).__name__
            reports.append(dict(event_id=event_id, status='blocked', reason=reason[:160]))
    return dict(manifest_sha256=expected_sha, events=reports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    report = execute(options.manifest, options.sha256, apply=options.apply)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if any(e['status'] == 'blocked' for e in report['events']) else 0


if __name__ == '__main__':
    raise SystemExit(main())

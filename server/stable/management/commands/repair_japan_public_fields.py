"""从当前已发布官方 revision 补正日本公开投影；固定清单、默认回滚、不联网。"""
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from stable import models
from stable.services.japan_public_fields import japan_source, result_popularity, fill_result_time
from stable.services.race_event_public_cache import invalidate_public_race_cache
from stable.services.race_source_identity import event_snapshot


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def projection_snapshot(event):
    return digest(dict(identity=event_snapshot(event), time=[event.race_datetime, event.local_start_time, event.timezone_name],
        results=list(event.results.order_by('pk').values('id', 'horse_number', 'horse_name', 'running_status',
            'popularity', 'carried_weight', 'margin', 'source_refs', 'raw_payload')),
        runners=list(event.runners.order_by('pk').values('id', 'horse_number', 'horse_name', 'running_status',
            'carried_weight', 'source_refs', 'manual_lock_flags'))))


def execute(path, expected_sha256, *, apply=False, now=None):
    path = Path(path); raw = path.read_bytes(); sha = hashlib.sha256(raw).hexdigest()
    if sha != expected_sha256:
        raise ValueError('manifest_digest')
    manifest = json.loads(raw); items = manifest.get('items', [])
    if (manifest.get('action') != 'repair_japan_public_fields' or manifest.get('schema_version') != 1
        or not 1 <= len(items) <= 1000 or len({r['event_id'] for r in items}) != len(items)):
        raise ValueError('manifest_scope')
    now = now or timezone.now()
    with transaction.atomic():
        receipt = models.OperationLog.objects.filter(action_type='japan_fields_repair', target_type='manifest', target_id=sha).first()
        if receipt:
            return dict(action='replay', manifest_sha256=sha, events=json.loads(receipt.detail)['events'])
        report = []
        for spec in sorted(items, key=lambda r: r['event_id']):
            event = models.RaceEvent.objects.select_for_update().get(pk=spec['event_id'])
            control = models.RaceEventProjectionControl.objects.select_for_update().get(event=event)
            if (event.country_region != 'japan' or event.status != 'finished'
                or control.write_owner != 'data_sync' or control.current_result_revision_id != spec['revision_id']
                or projection_snapshot(event) != spec['snapshot_sha256']):
                raise ValueError('projection_baseline_drift')
            if any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists():
                raise ValueError('manual_lock')
            lifecycle = models.RaceEventLifecycleControl.objects.filter(event=event).first()
            if lifecycle and lifecycle.manual_pause_reason:
                raise ValueError('manual_pause')
            revision = control.current_result_revision
            observation = revision.primary_observation
            source = observation.source_identity
            if not japan_source(source) or revision.published_at is None or revision.phase not in ('official', 'corrected'):
                raise ValueError('unpublished_japan_result')
            results = {r.horse_number: r for r in event.results.select_for_update()}
            runners = {r.horse_number: r for r in event.runners.select_for_update()}
            revision_items = list(revision.items.all())
            if len(results) != len(revision_items) or len(runners) != len(revision_items):
                raise ValueError('roster_mismatch')
            parsed_rows = None
            if spec.get('result_page'):
                from stable.management.commands.backfill_japan_results import read_artifact
                from stable.services.race_data_source_adapters import load_multisource_policy, parse_jra_observation, parse_nar_observation
                page = spec['result_page']; _, content = read_artifact(path.parent, page)
                route = load_multisource_policy(now=now).route_for(dict(provider=source.source_key,
                    region=source.region_code, identity_namespace=source.identity_namespace))
                if route is None:
                    raise ValueError('result_route')
                parser = parse_jra_observation if source.source_key == 'jra' else parse_nar_observation
                parsed = parser(content.decode('utf-8'), url=page['url'], route=route, now=now)
                if parsed['external_race_id'] != source.external_race_id or parsed.get('result_phase') != 'official':
                    raise ValueError('result_page_identity')
                parsed_rows = {r['number']: r for r in parsed['roster']}
                if set(parsed_rows) != set(results):
                    raise ValueError('result_page_roster')
            time_evidence = None
            if spec.get('time_card'):
                from stable.management.commands.backfill_japan_results import read_artifact
                from stable.services.race_data_source_adapters import load_multisource_policy, parse_nar_observation
                card = spec['time_card']; _, content = read_artifact(path.parent, card)
                policy = load_multisource_policy(now=now)
                route = policy.route_for(dict(provider='nar', region=source.region_code, identity_namespace=source.identity_namespace))
                if source.source_key != 'nar' or route is None:
                    raise ValueError('time_route')
                value = parse_nar_observation(content.decode('utf-8'), url=card['url'], route=route, now=now)
                if value['external_race_id'] != source.external_race_id or not value.get('off_time'):
                    raise ValueError('time_card_identity')
                time_evidence = dict(off_time=value['off_time'], url=card['url'], sha256=card['sha256'])
            for item in revision_items:
                result = results.get(item.horse_number); runner = runners.get(item.horse_number)
                if (not result or not runner or result.source_refs.get('revision_id') != revision.pk
                    or result.carried_weight != item.carried_weight or runner.carried_weight != item.carried_weight
                    or (runner.source_refs.get('field_units') or {}).get('carried_weight') not in (None, '', 'kg')
                    or result.margin != item.margin
                    or result.running_status != item.status
                    or runner.source_refs.get(source.source_key) != result.source_refs.get('external_runner_id')
                    or not result.source_refs.get('external_runner_id')):
                    raise ValueError('result_row_drift')
                field_provenance = item.field_provenance
                if parsed_rows is not None:
                    row = parsed_rows[item.horse_number]
                    if (row['status'] != item.status or row['reported_finish_position'] != item.reported_finish_position
                        or row['horse_name'] != result.horse_name or row['carried_weight'] != item.carried_weight
                        or row['margin'] != item.margin):
                        raise ValueError('result_page_facts_drift')
                    field_provenance = row['field_provenance']
                    result.raw_payload = {**result.raw_payload, 'public_fields_evidence': {
                        'source_url': page['url'], 'raw_sha256': page['sha256'],
                        'popularity': result_popularity(field_provenance)}}
                result.popularity = result_popularity(field_provenance)
                result.source_refs = {**result.source_refs, 'field_units': {
                    **result.source_refs.get('field_units', {}), 'carried_weight': 'kg', 'margin': 'length'}}
                result.save(update_fields=('popularity', 'source_refs', 'raw_payload', 'updated_at'))
                if any((runner.manual_lock_flags or {}).values()):
                    raise ValueError('runner_manual_lock')
                runner.running_status = item.status
                runner.source_refs = {**runner.source_refs, 'field_units': {
                    **runner.source_refs.get('field_units', {}), 'carried_weight': 'kg'}}
                runner.save(update_fields=('running_status', 'source_refs', 'updated_at'))
            time_changed = fill_result_time(event=event, observation=observation, revision=revision,
                now=now, time_evidence=time_evidence)
            report.append(dict(event_id=event.pk, rows=len(results), time_changed=time_changed,
                time=event.race_datetime.isoformat() if event.race_datetime else None))
        transaction.on_commit(invalidate_public_race_cache)
        result = dict(action='applied' if apply else 'dry_run', manifest_sha256=sha, events=report)
        models.OperationLog.objects.create(action_type='japan_fields_repair', target_type='manifest', target_id=sha,
            detail=json.dumps(result, ensure_ascii=False))
        if not apply:
            transaction.set_rollback(True)
        return result


class Command(BaseCommand):
    help = '按 SHA 清单补正日本公开字段；默认事务回滚。'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--expected-sha256', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            report = execute(options['manifest'], options['expected_sha256'], apply=options['apply'])
        except (ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False))

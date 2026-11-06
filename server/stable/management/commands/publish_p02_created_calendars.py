"""仅公开固定建档收据产生的基础日历页，不开启同步或发布赛果。"""
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from stable.models import HistoricalRaceEventTarget, RaceEvent, OperationLog
from stable.services.historical_race_batches import (
    materialization_snapshot, validate_historical_materialization,
    validate_materialized_historical_identity, _materialize_timezone,
)
from stable.services.historical_race_inventory import InventoryValidationError
from stable.management.commands.register_p02_canonical_names import digest


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--expected-sha256', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        raw=Path(options['manifest']).read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if sha!=options['expected_sha256']:raise CommandError('manifest_sha_mismatch')
        payload=json.loads(raw);items=payload.get('targets',[])
        if (payload.get('schema')!='p02-publish-created-calendars-v1' or not items
                or len({i['target_id'] for i in items})!=len(items)):
            raise CommandError('invalid_publication_manifest')
        with transaction.atomic():
            repair=OperationLog.objects.filter(action_type='p02_event_repairs_applied',target_type='manifest',
                target_id=payload['repair_manifest_sha256']).first()
            if not repair:raise CommandError('repair_receipt_missing')
            owned=json.loads(repair.detail)['target_event_ids']
            if set(owned)!={str(i['target_id']) for i in items}:
                raise CommandError('publication_target_set_mismatch')
            previous=OperationLog.objects.filter(action_type='p02_calendars_published',target_type='manifest',target_id=sha).first()
            events=[]
            for item in sorted(items,key=lambda i:i['target_id']):
                target=HistoricalRaceEventTarget.objects.select_for_update().get(pk=item['target_id'])
                if digest(materialization_snapshot(target))!=item['materialization_snapshot_sha256']:
                    raise CommandError('target_snapshot_drift')
                if not target.event_id or target.event_id!=owned[str(target.pk)]:
                    raise CommandError('target_event_binding_drift')
                event=RaceEvent.objects.select_for_update().get(pk=target.event_id)
                try:
                    identity,slug=validate_historical_materialization(target,scheduled=True)
                    validate_materialized_historical_identity(event,target=target,identity=identity,slug=slug)
                except InventoryValidationError as exc:
                    raise CommandError(str(exc)) from exc
                expected={field:getattr(target,field) for field in (
                    'original_name','racecourse','grade_text','normalized_grade','surface','distance_text','local_date')}
                expected.update(race_series_id=target.race_series_id,series_key=target.race_series.key,
                    chinese_name=target.chinese_name or target.race_series.chinese_name or target.original_name,
                    timezone_name=_materialize_timezone(target),status='scheduled',
                    visibility_status='published' if previous else 'draft',
                    source_refs={**target.source_refs,'historical_target_id':target.pk,'inventory_artifact_sha256':target.artifact_sha256})
                if any(getattr(event,field)!=value for field,value in expected.items()):
                    raise CommandError('created_event_field_drift')
                # 详情页会直接读这些关联行；日历发布不能连带公开未获准的名单/赛果。
                if event.runners.exists() or event.results.exists():
                    raise CommandError('calendar_only_requires_empty_runner_and_result_rows')
                events.append(event)
            if options['apply'] and not previous:
                for event in events:
                    event.visibility_status='published'
                    event.save(update_fields={'visibility_status','updated_at'})
                OperationLog.objects.create(action_type='p02_calendars_published',target_type='manifest',target_id=sha,
                    detail=json.dumps({'event_ids':[e.pk for e in events],
                        'repair_manifest_sha256':payload['repair_manifest_sha256'],'manifest_sha256':sha}))
        self.stdout.write(json.dumps({'manifest_sha256':sha,'event_ids':[e.pk for e in events],
            'applied':bool(options['apply']),'sync_settings_changed':False}))

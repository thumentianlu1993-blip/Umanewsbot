"""One-off, SHA-bound identity corrections for the September race-section audit."""
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from stable import models

TASK = 'repair_race_section_identities'
FIELDS = ('year','slug','original_name','country_region','racecourse','local_date','timezone_name')
TARGETS = {829: ('PRIX DE CHAMBLY', {'PRIX DE CHAMBL Y','PRIX DE CHAMBLY'}),
           104: ('オールカマー', {'産経賞オールカマー'})}


def identity(event):
    return {key: (getattr(event,key).isoformat() if key=='local_date' and event.local_date else getattr(event,key))
            for key in FIELDS}


@transaction.atomic
def repair_identities(manifest, *, manifest_sha, apply=False):
    rows=manifest.get('repairs') if isinstance(manifest,dict) else None
    if (not isinstance(manifest,dict) or manifest.get('schema_version') != 1 or
        not isinstance(rows,list) or not 1 <= len(rows) <= 2 or
        not all(isinstance(row,dict) for row in rows)):
        raise ValueError('invalid_identity_repair_manifest')
    ids=[row.get('event_id') for row in rows]
    if any(type(pk) is not int or pk not in TARGETS for pk in ids) or len(set(ids))!=len(ids):
        raise ValueError('invalid_identity_repair_scope')
    recorded=models.TaskExecutionLog.objects.filter(task_name=TASK,status='success',payload__manifest_sha256=manifest_sha).exists()
    changes=[]
    replayed=[]
    audit=[]
    for row in sorted(rows,key=lambda value:value['event_id']):
        pk=row['event_id']
        if models.RaceEventLifecycleControl.objects.select_for_update().filter(event_id=pk).exists():
            raise ValueError('identity_repair_lifecycle_owned')
        event=models.RaceEvent.objects.select_for_update().filter(pk=pk).first()
        if event is None: raise ValueError('identity_repair_event_missing')
        control=models.RaceEventProjectionControl.objects.select_for_update().filter(event=event).first()
        if (control and control.write_owner!='unmanaged') or models.RaceDataSyncEnrollment.objects.filter(event=event,state='enrolled').exists():
            raise ValueError('identity_repair_managed_owner')
        if any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists():
            raise ValueError('identity_repair_manual_lock')
        desired, aliases=TARGETS[pk]
        if row.get('original_name',desired)!=desired or set(row.get('aliases',[]))!=aliases:
            raise ValueError('identity_repair_unapproved_change')
        expected=row.get('before',{})
        if set(expected)!=set(FIELDS): raise ValueError('identity_repair_baseline_incomplete')
        after={**expected,'original_name':desired}
        current=identity(event)
        existing=list(event.aliases.filter(text__in=aliases))
        present={alias.text for alias in existing if alias.is_active}
        inactive={alias.text for alias in existing if not alias.is_active}
        if (aliases-present) & inactive: raise ValueError('identity_repair_inactive_alias')
        language='ja' if pk==104 else 'fr'
        additions=[{'text':text,'source_language':language} for text in sorted(aliases-present)]
        if recorded and current==after and aliases<=present:
            replayed.append(pk)
            continue
        if current!=expected: raise ValueError('identity_repair_baseline_drift')
        changes.append(pk)
        audit.append({'event_id':pk,'before':current,'after':after,'added_aliases':additions})
        if apply:
            event.original_name=desired
            event.save(update_fields=['original_name','updated_at'])
            for alias in additions:
                models.RaceEventAlias.objects.create(event=event,**alias,
                    is_active=True,alias_type='alias',source=TASK)
    if apply and changes:
        models.TaskExecutionLog.objects.create(task_name=TASK,status='success',
            payload={'manifest_sha256':manifest_sha,'events':audit})
    return {'mode':'apply' if apply else 'dry_run','changed':changes,'replayed':replayed,'events':audit}


class Command(BaseCommand):
    help='默认只读核对 829/104 精确身份修复；写入需 SHA 绑定并显式 --apply。'

    def add_arguments(self, parser):
        parser.add_argument('--manifest',required=True)
        parser.add_argument('--sha256',required=True)
        parser.add_argument('--apply',action='store_true')

    def handle(self,**options):
        try:
            raw=Path(options['manifest']).read_bytes()
            if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=options['sha256']:
                raise ValueError('identity_repair_manifest_sha_mismatch')
            result=repair_identities(json.loads(raw),manifest_sha=options['sha256'],apply=options['apply'])
        except (OSError,ValueError,TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result,ensure_ascii=False,sort_keys=True))

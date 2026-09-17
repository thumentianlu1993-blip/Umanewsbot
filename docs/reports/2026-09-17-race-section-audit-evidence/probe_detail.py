import json
from django.db import connection,transaction
from django.conf import settings
from django.utils import timezone
from stable import models as m
out={'now':str(timezone.now()),'release':settings.UMANEWS_RELEASE_COMMIT}
ids=[828,829,830,104,105]
with transaction.atomic():
 with connection.cursor() as c:
  c.execute('SET TRANSACTION READ ONLY'); c.execute("SET LOCAL statement_timeout='12s'")
 out['tracking']=list(m.RaceEventLiveTracking.objects.filter(event_id__in=ids).values('event_id','state','tracking_enabled','next_poll_at','last_attempt_at','last_success_at','consecutive_failures','circuit_reason','checkpoint_payload'))
 out['checkpoints']=list(m.RaceEventLiveProviderCheckpoint.objects.filter(tracking__event_id__in=ids).values('tracking__event_id','data_kind','next_poll_at','last_attempt_at','last_success_at','circuit_reason','consecutive_failures'))
 out['observations']=list(m.RaceResultObservation.objects.filter(source_identity__event_id__in=ids).values('id','source_identity__event_id','observed_at','http_status','result_phase','error_code','parse_warnings').order_by('-id')[:20])
 out['incidents']=list(m.RaceLiveAlertIncident.objects.filter(scope_key__in=[str(x) for x in ids]).values('scope_key','scope_type','status','alert_type','details','last_error_code','delivery_attempts','alert_sent_at','opened_at')[:20])
 out['transitions']=list(m.RaceEventLifecycleTransition.objects.filter(event_id__in=ids).values('event_id','from_status','to_status','reason_code','created_at')[:15])
 out['source_events']=list(m.RaceEvent.objects.filter(id__in=ids).values('id','racecourse','source_refs','manual_lock_flags'))
 out['aliases']=list(m.RaceEventAlias.objects.filter(event_id__in=ids).values())
print(json.dumps(out,default=str,ensure_ascii=False,indent=2))

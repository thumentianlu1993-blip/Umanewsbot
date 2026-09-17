import json,datetime
from django.conf import settings
from django.db import connection,transaction
from django.db.models import Count,Q,Exists,OuterRef
from django.utils import timezone
from stable.models import RaceEvent,RaceEventResult,RaceEventRunner,RaceDataSyncEnrollment,RaceEventLifecycleControl,RaceResultSourceIdentity,TaskExecutionLog
out={}
with transaction.atomic():
 with connection.cursor() as c:
  c.execute('SET TRANSACTION READ ONLY')
  c.execute("SET LOCAL statement_timeout = '12s'")
 out['now']=timezone.now()
 out['settings']={k:getattr(settings,k) for k in dir(settings) if (k.startswith('RACE_DATA_SYNC_') or k in ['RELEASE_COMMIT','RACE_EVENT_LIFECYCLE_MODE','RACE_EVENT_LIFECYCLE_ENABLED']) and isinstance(getattr(settings,k),(bool,int)) or k in ['RELEASE_COMMIT','RACE_EVENT_LIFECYCLE_MODE']}
 fields=['id','year','slug','chinese_name','original_name','country_region','normalized_grade','local_date','local_start_time','race_datetime','timezone_name','status','visibility_status','result_confirmed_at','data_quality_status']
 qs=RaceEvent.objects.filter(visibility_status='published').exclude(canonical_product_links__is_active=True)
 out['near_events']=list(qs.filter(local_date__range=['2026-09-14','2026-09-23']).values(*fields).order_by('local_date','id')[:100])
 ids=[r['id'] for r in out['near_events']]
 out['enrollments']=list(RaceDataSyncEnrollment.objects.filter(event_id__in=ids).values('event_id','state','reason_code','source_identity_id','created_at','updated_at'))
 out['controls']=list(RaceEventLifecycleControl.objects.filter(event_id__in=ids).values('event_id','mode','next_refresh_at','last_attempt_at','last_success_at','last_result_code','consecutive_failures','manual_pause_reason'))
 out['identities']=list(RaceResultSourceIdentity.objects.filter(event_id__in=ids).values('event_id','source_key','region_code','external_race_id','review_status','automation_allowed'))
 out['result_counts']=list(RaceEventResult.objects.filter(event_id__in=ids).values('event_id','is_confirmed').annotate(n=Count('id')))
 out['runner_counts']=list(RaceEventRunner.objects.filter(event_id__in=ids).values('event_id').annotate(n=Count('id')))
 past=qs.filter(local_date__lt='2026-09-17')
 out['past_status']=list(past.values('status').annotate(n=Count('id')).order_by('status'))
 stale=past.filter(status='scheduled')
 out['stale_years']=list(stale.values('year').annotate(n=Count('id')).order_by('-year'))
 out['stale_regions']=list(stale.values('country_region').annotate(n=Count('id')).order_by('country_region'))
 out['stale_counts']=stale.aggregate(total=Count('id'),no_datetime=Count('id',filter=Q(race_datetime__isnull=True)),no_control=Count('id',filter=Q(lifecycle_control__isnull=True)),no_enrollment=Count('id',filter=Q(race_data_sync_enrollment__isnull=True)))
 out['stale_with_confirmed_results']=stale.filter(Exists(RaceEventResult.objects.filter(event_id=OuterRef('pk'),is_confirmed=True))).count()
 out['stale_samples']=list(stale.values(*fields).order_by('-local_date')[:12])
 out['sync_enrollment_summary']=list(RaceDataSyncEnrollment.objects.values('state').annotate(n=Count('id')))
 out['control_summary']=list(RaceEventLifecycleControl.objects.values('mode','last_result_code').annotate(n=Count('id')))
 out['recent_task_summary']=list(TaskExecutionLog.objects.filter(started_at__gte=timezone.now()-datetime.timedelta(hours=12),task_name__icontains='race').values('task_name','status').annotate(n=Count('id')))
 out['task_samples']=list(TaskExecutionLog.objects.filter(task_name__icontains='discov').values('id','task_name','status','started_at','payload').order_by('-id')[:4])
print(json.dumps(out,default=str,ensure_ascii=False,indent=2))

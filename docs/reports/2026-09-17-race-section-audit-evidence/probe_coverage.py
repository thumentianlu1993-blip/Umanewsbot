import json
from django.db import connection,transaction
from django.db.models import Count,Q,Min,Max
from stable import models as m
out={}
with transaction.atomic():
 with connection.cursor() as c:
  c.execute('SET TRANSACTION READ ONLY');c.execute("SET LOCAL statement_timeout='12s'")
 q=m.RaceEvent.objects.filter(visibility_status='published').exclude(canonical_product_links__is_active=True)
 out['published_status']=list(q.values('status').annotate(n=Count('id')).order_by('status'))
 out['scheduled_missing_date_by_year']=list(q.filter(status='scheduled',local_date__isnull=True).values('year').annotate(n=Count('id')).order_by('year'))
 out['stale_date_range']=q.filter(status='scheduled',local_date__lt='2026-09-17').aggregate(first=Min('local_date'),last=Max('local_date'))
 out['past_year_status']=list(q.filter(year__lt=2026).values('status').annotate(n=Count('id')).order_by('status'))
 out['upcoming_7day']=q.filter(local_date__range=['2026-09-18','2026-09-24']).aggregate(total=Count('id'),no_time=Count('id',filter=Q(race_datetime__isnull=True)),no_enrollment=Count('id',filter=Q(race_data_sync_enrollment__isnull=True)))
 out['recent_snapshot_failures']=list(m.RaceDataSnapshotLease.objects.filter(state='failed').values('id','updated_at','error_code').order_by('-updated_at')[:10])
print(json.dumps(out,default=str,ensure_ascii=False,indent=2))

"""只读展示单场赛事采集诊断与原件存在性；不输出响应体或发起请求。"""
import json
from django.core.management.base import BaseCommand, CommandError
from stable import models
from stable.services.race_collection_failures import inspect_evidence


class Command(BaseCommand):
    help = '只读核查赛事采集失败分类、重试和原件状态'

    def add_arguments(self, parser):
        parser.add_argument('--event-id', type=int, required=True)

    def handle(self, *args, **options):
        try:
            event = models.RaceEvent.objects.only('id', 'source_refs').get(pk=options['event_id'])
        except models.RaceEvent.DoesNotExist:
            raise CommandError('赛事不存在') from None
        rows = []

        def append(lane, source, diagnostic, due=None):
            if not isinstance(diagnostic, dict) or not diagnostic:
                return
            rows.append(dict(lane=lane, source=source, next_poll_at=due, diagnostic=diagnostic,
                             evidence_now=inspect_evidence(diagnostic.get('evidence', {}).get('sha256'))))

        for row in models.RaceEventLiveProviderCheckpoint.objects.filter(tracking__event=event).order_by('source_key', 'data_kind'):
            append(row.data_kind, row.source_key, row.failure_diagnostic, row.next_poll_at)
        refs = event.source_refs if isinstance(event.source_refs, dict) else {}
        for source, state in refs.get('pre_race_checks', {}).items():
            append('pre_race', source, state.get('failure_diagnostic'), state.get('next_poll_at'))
        discovery = refs.get('source_discovery_v2', {})
        for route, diagnostic in discovery.get('failure_diagnostics', {}).items():
            append('discovery', route, diagnostic, discovery.get('next_poll_at'))
        self.stdout.write(json.dumps(dict(event_id=event.pk, diagnostics=rows), ensure_ascii=False, default=str))

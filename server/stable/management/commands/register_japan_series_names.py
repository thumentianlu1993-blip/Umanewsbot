"""按固定清单转存已审核系列正式名称；默认仅检查，不抓取、不发布赛事。"""
import hashlib
import json
import unicodedata
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from stable.models import RaceSeries, RaceEvent, RaceSeriesName, OperationLog


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class Command(BaseCommand):
    help = '校验或登记日本赛事清单中已有审核记录的正式名称，默认dry-run'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--expected-sha256', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        raw = Path(options['manifest']).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != options['expected_sha256']:
            raise CommandError('manifest_sha_mismatch')
        payload = json.loads(raw)
        items = payload.get('items', [])
        if not items or len(items) != payload.get('count') or len({(x['series_id'], x['valid_from_year']) for x in items}) != len(items):
            raise CommandError('invalid_manifest_items')
        created = 0
        with transaction.atomic():
            # 发布包必须在单一协调者停写窗口中执行；锁定固定事件和系列防止审核状态漂移。
            events = {e.pk:e for e in RaceEvent.objects.select_for_update().filter(
                pk__in=[x['event_id'] for x in items]).order_by('pk')}
            series = {s.pk:s for s in RaceSeries.objects.select_for_update().filter(
                pk__in=[x['series_id'] for x in items]).order_by('pk')}
            staged = []
            manifest_names = set()
            for item in items:
                s = series.get(item['series_id']); event = events.get(item['event_id'])
                if not s or not event or event.race_series_id != s.pk or event.edition_year != item.get('valid_from_year') or event.country_region != 'japan':
                    raise CommandError('event_series_identity_drift')
                snapshot = {k:getattr(s,k) for k in (
                    'id','key','canonical_name_original','country_region','review_status','source_refs')}
                expected = item.get('preconditions', {})
                if (digest(snapshot) != expected.get('series_sha256') or s.review_status != 'approved'
                        or not s.source_refs or expected.get('event_edition_year') != event.edition_year):
                    raise CommandError('series_snapshot_drift')
                text = unicodedata.normalize('NFKC', s.canonical_name_original)
                if (item.get('action') != 'register_existing_reviewed_canonical_name'
                        or item.get('text') != text or item.get('name_type') != 'canonical'
                        or item.get('valid_from_year') != event.edition_year or item.get('valid_to_year') != event.edition_year):
                    raise CommandError('only_existing_canonical_name_allowed')
                refs = item.get('source_refs', {})
                if (refs.get('basis') != 'existing_approved_series_canonical'
                        or refs.get('series_source_refs') != s.source_refs
                        or refs.get('series_source_refs_sha256') != digest(s.source_refs)):
                    raise CommandError('source_evidence_drift')
                normalized = ' '.join(text.casefold().split())
                key = (s.country_region, normalized, event.edition_year)
                if key in manifest_names:
                    raise CommandError('manifest_name_conflict')
                manifest_names.add(key)
                overlapping = RaceSeriesName.objects.filter(
                    series__country_region=s.country_region, normalized_text=normalized, is_active=True,
                ).filter(Q(valid_from_year=0)|Q(valid_from_year__lte=event.edition_year)).filter(
                    Q(valid_to_year=0)|Q(valid_to_year__gte=event.edition_year))
                if overlapping.exclude(series_id=s.pk).exists():
                    raise CommandError('cross_series_name_conflict')
                existing = RaceSeriesName.objects.filter(series_id=s.pk, source_language='',
                    normalized_text=normalized, valid_from_year=event.edition_year).first()
                if existing:
                    if (existing.text != text or existing.valid_to_year != event.edition_year or not existing.is_active
                            or existing.name_type != 'canonical' or existing.source_refs != refs):
                        raise CommandError('existing_name_drift')
                else:
                    row = RaceSeriesName(series=s, text=text, normalized_text=normalized, name_type='canonical',
                        valid_from_year=event.edition_year, valid_to_year=event.edition_year, source_refs=refs)
                    row.full_clean()
                    staged.append(row)
            created = len(staged)
            if options['apply']:
                for row in staged:
                    row.save()
                OperationLog.objects.get_or_create(action_type='japan_canonical_names_registered',
                    target_type='manifest', target_id=sha, defaults={'detail':json.dumps({'count':len(items),'manifest_sha256':sha})})
        self.stdout.write(json.dumps({'manifest_sha256':sha,'checked':len(items),
            'would_create':created,'applied':bool(options['apply'])}))

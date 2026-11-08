"""固定证据清单的名称登记；只由最终停写发布窗口调用，默认dry-run。"""
import hashlib
import json
import unicodedata
from pathlib import Path
from django.db import transaction
from django.db.models import Q
from stable.models import RaceEvent, RaceSeries, RaceSeriesName, OperationLog


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def apply_manifest(path, expected_sha256, *, apply=False):
    path = Path(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != expected_sha256:
        raise ValueError('alias_manifest_digest')
    manifest = json.loads(raw)
    items = manifest['items']
    if manifest.get('action') != 'create_evidenced_RaceSeriesName' or not 1 <= len(items) <= 1000:
        raise ValueError('alias_manifest_scope')
    # 原始证据随包传入，名称本身由清单逐条审核，不做模糊匹配。
    for item in items:
        refs = item['source_refs']
        evidence = (path.parent / refs['artifact']).resolve()
        if not evidence.is_relative_to(path.parent.resolve()) or hashlib.sha256(evidence.read_bytes()).hexdigest() != refs['raw_sha256']:
            raise ValueError('alias_evidence_digest')
        if (not refs.get('url', '').startswith(('https://www.jra.go.jp/', 'https://www.keiba.go.jp/')) or not refs.get('basis')
                or type(item['valid_from_year']) is not int or item['valid_from_year'] < 1 or item['valid_to_year'] != item['valid_from_year']
                or item['text'] != unicodedata.normalize('NFKC', item['raw_source_name'])):
            raise ValueError('alias_evidence_scope')
    staged = []
    seen = {}
    with transaction.atomic():
        events = {e.pk: e for e in RaceEvent.objects.select_for_update().filter(pk__in=[i['event_id'] for i in items]).order_by('pk')}
        series = {s.pk: s for s in RaceSeries.objects.select_for_update().filter(pk__in=[i['series_id'] for i in items]).order_by('pk')}
        for item in items:
            event, s = events.get(item['event_id']), series.get(item['series_id'])
            if not event or not s or event.race_series_id != s.pk or event.country_region != 'japan' or s.country_region != 'japan' or event.edition_year != item['valid_from_year']:
                raise ValueError('alias_event_series_drift')
            actual = {k: (getattr(event, k).isoformat() if k == 'local_date' and getattr(event,k) else getattr(event,k)) for k in ('original_name', 'edition_year', 'local_date', 'racecourse')}
            snapshot = {k: getattr(s,k) for k in ('id','key','canonical_name_original','country_region','review_status','source_refs')}
            if actual != item['expected_event'] or s.review_status != 'approved' or not s.source_refs or digest(snapshot) != item['series_sha256']:
                raise ValueError('alias_identity_snapshot_drift')
            normalized = ' '.join(item['text'].casefold().split())
            key = (s.country_region, normalized, event.edition_year)
            if key in seen:
                raise ValueError('alias_manifest_duplicate_or_conflict')
            seen[key] = s.pk
            overlap = RaceSeriesName.objects.filter(series__country_region=s.country_region, normalized_text=normalized, is_active=True).filter(Q(valid_from_year=0)|Q(valid_from_year__lte=event.edition_year)).filter(Q(valid_to_year=0)|Q(valid_to_year__gte=event.edition_year))
            if overlap.exclude(series_id=s.pk).exists():
                raise ValueError('alias_cross_series_conflict')
            values = dict(text=item['text'], name_type='alias', valid_to_year=event.edition_year, is_active=True, source_refs=item['source_refs'])
            existing = RaceSeriesName.objects.filter(series=s, source_language=item['source_language'], normalized_text=normalized, valid_from_year=event.edition_year).first()
            if existing:
                if any(getattr(existing,k) != v for k,v in values.items()):
                    raise ValueError('alias_existing_drift')
            else:
                row = RaceSeriesName(series=s, source_language=item['source_language'], normalized_text=normalized, valid_from_year=event.edition_year, **values)
                row.full_clean()
                staged.append(row)
        if apply:
            for row in staged:
                row.save()
            OperationLog.objects.get_or_create(action_type='japan_source_names_registered', target_type='manifest', target_id=sha, defaults={'detail': json.dumps({'count':len(items), 'manifest_sha256':sha})})
    return {'manifest_sha256':sha,'checked':len(items),'would_create':len(staged),'applied':apply}


from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '固定日本赛事来源名称清单校验/登记；默认dry-run'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--expected-sha256', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            result=apply_manifest(options['manifest'],options['expected_sha256'],apply=options['apply'])
        except (ValueError,KeyError,TypeError,OSError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result,ensure_ascii=False))

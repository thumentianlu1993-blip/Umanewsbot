#!/usr/bin/env python3
"""仅导入已审核的香港2026/27赛季资料包；默认只读，禁止联网采集。"""
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from stable import models as m

ACTION = 'import_hkjc_2627'
HK = ZoneInfo('Asia/Hong_Kong')
API = 'https://racing.hkjc.com/contentAsset/api/getSeasonRaces'
PDF = 'https://racing.hkjc.com/racing/content/PDF/RaceCard/20260906_starter_all.pdf'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def bytes_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plain(text):
    return BeautifulSoup(text, 'html.parser').get_text(' ', strip=True)


def event_snapshot(pk):
    return {'event': m.RaceEvent.objects.values().get(pk=pk),
            'results': list(m.RaceEventResult.objects.filter(event_id=pk).order_by('id').values()),
            'runners': list(m.RaceEventRunner.objects.filter(event_id=pk).order_by('id').values())}


def result_table(path):
    soup = BeautifulSoup(Path(path).read_text(), 'html.parser')
    tables = [t for t in soup.find_all('table')
              if ('Finish Time' in t.get_text(' ', strip=True) and 'Horse No.' in t.get_text(' ', strip=True))
              or ('完成 時間' in t.get_text(' ', strip=True) and '馬號' in t.get_text(' ', strip=True))]
    require(len(tables) == 1, 'result table missing/ambiguous')
    rows = [[c.get_text(' ', strip=True) for c in tr.find_all('td', recursive=False)]
            for tr in tables[0].find_all('tr')[1:]]
    require(len(rows) == 6 and all(len(r) == 12 for r in rows), 'requires all six official finishers')
    return rows


def validate(manifest, source_dir, today):
    require(manifest['schema'] == 'reviewed-hkjc-2627-v1' and manifest['season'] == '2026/27', 'scope')
    require(manifest['as_of'] == '2026-09-18' and manifest['reviewer'], 'review metadata')
    require('2026-09-18' <= today < '2026-09-27', 'reviewed source package expired')
    sources = manifest['sources']
    require(set(sources) == {'en', 'zh', 'result_en', 'result_zh', 'programme'}, 'source set')
    for key, source in sources.items():
        expected_url = API if key in {'en', 'zh'} else PDF if key == 'programme' else (
            'https://racing.hkjc.com/' + ('en-us' if key == 'result_en' else 'zh-hk') +
            '/local/information/localresults?racedate=2026/09/06&Racecourse=ST&RaceNo=3')
        require(source['url'] == expected_url, 'unreviewed source URL')
        require(Path(source['file']).name == source['file'], 'source path must be a basename')
        require(bytes_sha(source_dir / source['file']) == source['sha256'], 'source SHA drift')
        fetched = datetime.fromisoformat(source['fetched_at'])
        require(fetched.utcoffset() is not None and fetched.date().isoformat() == '2026-09-18', 'fetch date')
    en, zh = [json.loads((source_dir / sources[lang]['file']).read_text())['data']['raceList'] for lang in ('en', 'zh')]
    entries = manifest['events']
    require(len(en) == len(zh) == len(entries) == 35, 'requires complete 35-race list')
    require(Counter(r['grade'] for r in entries) == {'G1': 12, 'G2': 7, 'G3': 13, '4YO': 3}, 'grade coverage')
    require(len({r['series']['key'] for r in entries}) == 35, 'duplicate series')
    require([r['index'] for r in entries] == list(range(35)), 'source order')
    require([r['index'] for r in entries if r['existing_event_id']] == [9]
            and entries[9]['existing_event_id'] == 2, 'existing scope')
    require(entries[9]['series']['id'] == 5980 and entries[9]['date'] == '2026-12-13', 'existing identity')
    require([r['index'] for r in entries if r['series']['id'] is None] == [0], 'new series scope')
    require(manifest['completed_start'] == '2026-09-06T13:30:00+08:00', 'reviewed PDF start time')
    require(manifest['programme_evidence'] == {'start_page': 18, 'fixture_pages': [52, 53],
            'surface': 'turf', 'going': '好地至快地', 'course_layout': 'A'}, 'PDF evidence')
    fields = []
    for row, english, chinese in zip(entries, en, zh):
        epoch = english['raceDate']['dateValue']
        require(epoch == chinese['raceDate']['dateValue'], 'bilingual date mismatch')
        local = datetime.fromtimestamp(epoch / 1000, HK)
        require(local.strftime('%H:%M:%S') == '00:00:00', 'calendar date semantics changed')
        require(local.date().isoformat() == row['date'], 'date mismatch')
        require(plain(english['raceName']['value']) == row['name_en'] and
                chinese['raceName']['value'] == row['name_zh_hant'], 'bilingual name mismatch')
        require(english['class']['value'] == row['grade'] and chinese['class']['value'] ==
                {'G1': '一級賽', 'G2': '二級賽', 'G3': '三級賽', '4YO': '四歲馬經典賽事系列'}[row['grade']], 'grade mismatch')
        require(english['distance']['value'] == chinese['distance']['value'] == row['distance'], 'distance mismatch')
        require(english['prizeMoney']['value'] == chinese['prizeMoney']['value'] == row['prize_hkd'], 'prize mismatch')
        require(row['racecourse'] == ('Happy Valley' if row['index'] == 15 else 'Sha Tin'), 'reviewed PDF course mismatch')
        require(bool(row['name_zh']) and row['name_zh'] == row['series']['chinese_name'], 'display name missing')
        finished = row['index'] == 0
        require((row['date'] < today) == finished, 'past event needs reviewed results')
        refs = {'source_provider': 'HKJC', 'source_authority': 'official', 'season_label': '2026/27',
                'source_url': API, 'source_scope': 'PatternRace', 'reviewed_import': ACTION,
                'sources': sources, 'source_index': row['index'], 'official_name_hant': row['name_zh_hant'],
                'prize_hkd': row['prize_hkd'], 'programme_pages': [18] if finished else [52, 53]}
        if finished:
            refs['result_url'] = sources['result_zh']['url']
        fields.append(dict(year=local.year, edition_year=local.year,
            slug=f"{row['series']['key']}-{local.year}", series_key=row['series']['key'],
            original_name=row['name_en'], chinese_name=row['name_zh'], country_region='hong_kong',
            racecourse=row['racecourse'], grade_text=row['grade'],
            normalized_grade='OTHER' if row['grade'] == '4YO' else row['grade'],
            surface='turf', distance_text=row['distance']+'m', timezone_name='Asia/Hong_Kong',
            local_date=local.date(), local_start_time=datetime.fromisoformat(manifest['completed_start']).time() if finished else None,
            race_datetime=datetime.fromisoformat(manifest['completed_start']) if finished else None,
            priority='P0' if row['grade'] == 'G1' else 'P1' if row['grade'] in {'G2', '4YO'} else 'P2',
            status='finished' if finished else 'scheduled', visibility_status='published',
            data_quality_status='complete' if finished else 'partial',
            result_confirmed_at=datetime.fromisoformat(sources['result_zh']['fetched_at']) if finished else None,
            eligibility_text='3岁及以上' if finished else '4岁' if row['grade'] == '4YO' else '',
            source_refs=refs))
    require(Counter(f['year'] for f in fields) == {2026: 13, 2027: 22}, 'civil year coverage')
    raw_zh, raw_en = [result_table(source_dir / sources['result_'+lang]['file']) for lang in ('zh', 'en')]
    require(len(manifest['results']) == 6, 'complete results required')
    for rank, (row, z, e) in enumerate(zip(manifest['results'], raw_zh, raw_en), 1):
        require(row['raw_zh'] == z and row['raw_en'] == e, 'result source drift')
        require(row['rank'] == rank and z[0] == e[0] == str(rank), 'rank mismatch')
        require(row['number'] == z[1] == e[1], 'number mismatch')
        require(row['horse_code'] == re.search(r'\(([A-Z]\d+)\)', z[2]).group(1)
                == re.search(r'\(([A-Z]\d+)\)', e[2]).group(1), 'horse identity mismatch')
        require(all(z[n] == e[n] for n in (5, 6, 7, 8, 9, 10, 11)), 'bilingual result mismatch')
        require(all(row[k] for k in ('horse_name', 'jockey_name', 'trainer_name')), 'display name missing')
        require(re.fullmatch(r'https://racing\.hkjc\.com/zh-hk/local/information/horse\?horseid=HK_\d{4}_'+row['horse_code'], row['horse_url']), 'horse source URL')
    return fields


def check_database(manifest):
    require(digest(event_snapshot(2)) == manifest['existing_sha256'], 'existing Hong Kong Cup changed')
    for row in manifest['events']:
        s = row['series']
        if s['id']:
            actual = m.RaceSeries.objects.select_for_update().values(
                'id', 'key', 'canonical_name_original', 'chinese_name', 'country_region').get(pk=s['id'])
            require(actual == {**s, 'country_region': 'hong_kong'}, 'series mapping drift')
        else:
            require(not m.RaceSeries.objects.filter(Q(key=s['key']) | Q(country_region='hong_kong',
                    canonical_name_original=s['canonical_name_original'])).exists(), 'new series already exists')
        candidates = m.RaceEvent.objects.filter(country_region='hong_kong').filter(
            Q(race_series_id=s['id'], edition_year=int(row['date'][:4])) if s['id'] else Q(pk__in=[]))
        same_date = m.RaceEvent.objects.filter(country_region='hong_kong', local_date=row['date']).filter(
            Q(original_name__in=[row['name_en'], s['canonical_name_original']]) |
            Q(chinese_name__in=[row['name_zh'], row['name_zh_hant']]) | Q(series_key=s['key']))
        ids = set(candidates.values_list('id', flat=True)) | set(same_date.values_list('id', flat=True))
        require(ids == ({2} if row['existing_event_id'] else set()), 'duplicate event or series/year identity')


def run(manifest, source_dir, *, expected_sha, apply=False, today=None, fault_hook=None):
    require(digest(manifest) == expected_sha, 'manifest SHA mismatch')
    today = today or timezone.now().astimezone(HK).date().isoformat()
    fields = validate(manifest, Path(source_dir), today)
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '60s'")
                cursor.execute('SELECT pg_advisory_xact_lock(2627, 20260918)')
        from stable.services.historical_race_calendar_admission import assert_historical_calendar_write_admitted
        assert_historical_calendar_write_admitted()
        require(not m.ExternalDataImportLock.objects.filter(locked_by_run__isnull=False).exists(), 'external import active')
        require(not m.HistoricalBatchRun.objects.filter(status__in=['running', 'pausing', 'restoring']).exists(), 'historical import active')
        logs = list(m.OperationLog.objects.filter(action_type=ACTION, target_type='HKJCSeason', target_id='2627'))
        if logs:
            require(len(logs) == 1, 'multiple import receipts')
            receipt = json.loads(logs[0].detail)
            require(receipt['manifest_sha256'] == expected_sha, 'different manifest already applied')
            require(all(digest(event_snapshot(int(pk))) == sha for pk, sha in receipt['after_sha256'].items()), 'applied rows drifted')
            return {'status': 'already_applied', 'create_count': 34, 'event_ids': receipt['event_ids']}
        m.RaceEvent.objects.select_for_update().get(pk=2)
        check_database(manifest)
        if not apply:
            return {'status': 'dry_run', 'create_count': 34, 'preserve_ids': [2], 'results': 6, 'manifest_sha256': expected_sha}
        require(connection.vendor == 'postgresql', 'apply requires PostgreSQL transaction locks')
        from stable.services.race_events import apply_race_event_normalization
        created = []
        for row, values in zip(manifest['events'], fields):
            if row['existing_event_id']:
                continue
            series_id = row['series']['id']
            if series_id is None:
                series_values = {k: v for k, v in row['series'].items() if k != 'id'}
                series = m.RaceSeries(**series_values, country_region='hong_kong', status='active',
                    review_status='approved', source_refs=values['source_refs'])
                series.full_clean(); series.save(); series_id = series.pk
            event = m.RaceEvent(**values, race_series_id=series_id)
            event.full_clean(); event.save()
            apply_race_event_normalization(event)
            if row['index'] == 0:
                event.going_text = manifest['programme_evidence']['going']
                event.course_layout_text = 'A'
                event.save(update_fields=['going_text', 'course_layout_text'])
                for result in manifest['results']:
                    raw = result['raw_zh']
                    refs = {**values['source_refs'], 'primary': manifest['sources']['result_zh']['url'],
                            'hkjc_horse_code': result['horse_code'], 'horse_url': result['horse_url'],
                            'horse_name_hant': raw[2], 'body_weight': raw[6], 'running_positions': raw[9]}
                    common = dict(horse_number=result['number'], horse_name=result['horse_name'],
                        jockey_name=result['jockey_name'], trainer_name=result['trainer_name'],
                        carried_weight=raw[5], barrier=raw[7], odds_value=raw[11], running_status='finished',
                        source_refs=refs, raw_payload={'zh': raw, 'en': result['raw_en']})
                    rr = m.RaceEventResult(event=event, finish_position=result['rank'],
                        reported_finish_position=result['rank'], official_finish_position=result['rank'],
                        finish_time=raw[10], margin=raw[8], is_confirmed=True, **common)
                    rr.full_clean(); rr.save()
                    runner = m.RaceEventRunner(event=event, sort_order=int(result['number']),
                        external_runner_id='hkjc:'+result['horse_code'],
                        dynamic_updated_at=values['result_confirmed_at'], **common)
                    runner.full_clean(); runner.save()
            created.append(event.pk)
            if fault_hook:
                fault_hook(index=row['index'], event_id=event.pk)
        require(digest(event_snapshot(2)) == manifest['existing_sha256'], 'existing event mutated')
        after = {str(pk): digest(event_snapshot(pk)) for pk in [2, *created]}
        m.OperationLog.objects.create(action_type=ACTION, target_type='HKJCSeason', target_id='2627',
            detail=json.dumps({'manifest_sha256': expected_sha, 'script_sha256': bytes_sha(__file__),
                'event_ids': created, 'after_sha256': after, 'reviewer': manifest['reviewer']}, sort_keys=True))
        return {'status': 'applied', 'create_count': len(created), 'event_ids': created, 'results': 6,
                'manifest_sha256': expected_sha, 'after_sha256': after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--sources', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--script-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(bytes_sha(__file__) == args.script_sha256, 'script SHA mismatch')
    manifest = json.loads(Path(args.manifest).read_text())
    print(json.dumps(run(manifest, Path(args.sources), expected_sha=args.manifest_sha256,
                         apply=args.apply), ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()

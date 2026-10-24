"""exact2 secondary 固定视图；只验证既存输入，不执行 parser 或构造反例。"""
import csv
import hashlib
import io
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from tools.test_impact.fixture_inputs import _json, _regular, _relative, _require

RESOURCE_ID = 'b243-secondary2-v1'
MANIFEST_SHA256 = 'd564676417d45ed1b49dc08d4877cbde555b537939477f5c11fb070055052e93'
RESOURCE_PATH = Path('tools/test_impact/fixtures/secondary2')
READONLY_ROOT = Path('/source')/RESOURCE_PATH
NATIVE_IDS = (
    'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_nonempty_event_and_parsed_distance_conflict_becomes_validation_gap',
    'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_package_rejects_raw_candidate_without_validation_evidence',
)


def _canonical(value):
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _validate_discovery(smoke, refs, event, request, allowed_hosts):
    if smoke == 'smoke-japan-50556':
        detail = refs['detail_discovery']
        result = detail['urls']['result_url']
        _require(detail['adapter_key'] == request['source_provider'] == 'jra'
                 and result['source_provider'] == request['source_provider']
                 and result['url'] == request['source_url'], 'secondary JP detail discovery mismatch')
    elif smoke == 'smoke-hong_kong-49451':
        calendar = refs['calendar_discovery']
        url = urlsplit(calendar['calendar_source_url'])
        _require(calendar['calendar_source_provider'] == request['source_provider'] == 'hkjc'
                 and calendar['calendar_source_authority'] == 'official'
                 and calendar['edition_year'] == request['year'] == int(event['year'])
                 and calendar['local_date'] == request['local_date']
                 and url.scheme == 'https' and url.hostname in allowed_hosts and bool(url.path)
                 and url.username is None and url.password is None and not url.fragment,
                 'secondary HK calendar discovery mismatch')
    else:
        raise ValueError('fixture inputs: unadmitted secondary smoke')


def resource_environment(source_root):
    """仅由主准入器在 envclear/source/profile/exact2 验证后调用。"""
    root = _regular(source_root, str(RESOURCE_PATH/'manifest.json')).parent
    raw = (root/'manifest.json').read_bytes()
    _require(len(raw) <= 32768 and hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256,
             'secondary fixed manifest mismatch')
    manifest = _json(raw)
    _require(manifest['schema'] == 1 and manifest['id'] == RESOURCE_ID
             and manifest['native_ids'] == list(NATIVE_IDS)
             and len(manifest['files']) == 12 and manifest['view_file_count'] == 9
             and manifest['provenance_file_count'] == 3
             and manifest['readonly_root'] == str(READONLY_ROOT)
             and manifest['hk_cached_html_dependency'] is False, 'secondary schema mismatch')
    files = manifest['files']
    expected_files = set(files) | {'manifest.json'}
    expected_dirs = set()
    for name in expected_files:
        relative = _relative(name)
        expected_dirs.update(str(p) for p in relative.parents if str(p) != '.')
    actual_files, actual_dirs = set(), set()
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            path = Path(directory)/name
            _require(stat.S_ISDIR(path.lstat().st_mode), 'secondary symlink or non-directory')
            actual_dirs.add(str(path.relative_to(root)))
        for name in names:
            path = Path(directory)/name
            _require(stat.S_ISREG(path.lstat().st_mode), 'secondary symlink or non-regular file')
            actual_files.add(str(path.relative_to(root)))
    _require(actual_files == expected_files and actual_dirs == expected_dirs,
             'secondary missing or extra members')
    data = {}
    for name, identity in files.items():
        path = _regular(root, name)
        _require(path.stat().st_size == identity['bytes'], 'secondary size mismatch')
        body = path.read_bytes()
        _require(len(body) == identity['bytes'] and hashlib.sha256(body).hexdigest() == identity['sha256'],
                 'secondary hash mismatch')
        data[name] = body
    plan_sha = hashlib.sha256(data[manifest['plan']]).hexdigest()
    for record in manifest['descriptors']:
        original = _json(data[record['original']])
        view = _json(data[record['view']])
        _require(hashlib.sha256(data[record['original']]).hexdigest() == record['original_raw_sha256']
                 and _canonical(original) == record['original_canonical_sha256']
                 and hashlib.sha256(data[record['view']]).hexdigest() == record['git_view_raw_sha256']
                 and _canonical(view) == record['git_view_canonical_sha256'],
                 'secondary original/view identity mismatch')
        smoke = original['shard_id']
        events_name = 'smoke/events/'+smoke+'.csv'
        fragment_name = 'smoke/source_fragments/'+smoke+'.json'
        # Fresh JSON object, with only two runtime paths relocated. Historical identity fields stay original.
        expected = _json(data[record['original']])
        expected['adapter_inputs']['events_csv'] = str(READONLY_ROOT/events_name)
        expected['adapter_inputs']['source_fragment'] = str(READONLY_ROOT/fragment_name)
        _require(view == expected, 'secondary relocation changed non-path fields')
        inventory = [i for i in view['identities'] if i['role'] == 'plan']
        _require(len(inventory) == 1 and inventory[0]['sha256'] == plan_sha
                 and inventory[0]['size'] == len(data[manifest['plan']]), 'secondary plan identity mismatch')
        events = list(csv.DictReader(io.StringIO(data[events_name].decode('utf-8-sig'))))
        requests = _json(data[fragment_name])['requests']
        _require(len(events) == len(requests) == len(view['targets']) == 1,
                 'secondary single target required')
        event, request, target = events[0], requests[0], view['targets'][0]
        _require(str(event['target_id']) == str(request['target_id']) == str(target['target_id'])
                 and event['target_sha256'] == request['target_sha256'] == target['target_sha256'],
                 'secondary target identity mismatch')
        for role, name in (('events_csv', events_name), ('source_fragment', fragment_name)):
            identities = [i for i in view['identities'] if i['role'] == role]
            _require(len(identities) == 1 and identities[0]['sha256'] == files[name]['sha256']
                     and identities[0]['size'] == files[name]['bytes'], 'secondary adapter input identity mismatch')
        refs = _json(event['source_refs'])
        _validate_discovery(smoke, refs, event, request, view['request_policy']['allowed_hosts'])
        if smoke == 'smoke-japan-50556':
            cache_name = 'smoke/run/'+smoke+'/source-cache/source_cache_manifest.json'
            identities = list(_json(data[cache_name])['files'].values())
            _require(len(identities) == 1, 'secondary JRA single cache identity required')
            identity = identities[0]
            body_name = str(_relative(cache_name).parent/_relative(identity['path']))
            _require(body_name in files and identity['sha256'] == files[body_name]['sha256']
                     and int(identity['size']) == files[body_name]['bytes']
                     and identity['source_url'] == request['source_url'], 'secondary JRA cache identity mismatch')
        elif smoke == 'smoke-hong_kong-49451':
            # No HK cache manifest or HTML is opened or required by the expected-rejection native.
            candidates = [_json(line) for line in data['smoke/run/'+smoke+'/validated-candidates.jsonl'].splitlines() if line.strip()]
            _require(len(candidates) == 1, 'secondary HK single original candidate required')
            candidate = candidates[0]
            _require(str(candidate['target_id']) == str(target['target_id'])
                     and candidate['target_sha256'] == target['target_sha256']
                     and str(candidate['year']) == event['year'] and candidate['slug'] == event['slug']
                     and candidate['source_url'] == request['source_url']
                     and candidate['validation']['status'] == 'complete'
                     and str(candidate['validation']['target_id']) == str(target['target_id'])
                     and candidate['validation']['event']['source_url'] == request['source_url'],
                     'secondary HK original candidate identity mismatch')
        else:
            raise ValueError('fixture inputs: unadmitted secondary smoke')
    return {'HISTORICAL_DETAIL_DISTANCE_CACHE_RUN_ROOT': str(root/'smoke/run')}

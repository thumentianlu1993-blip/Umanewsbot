"""remaining exact3 的离线 fixture 绑定；不认证早期来源，不执行业务 parser。"""
import csv
import hashlib
import io
import os
from pathlib import Path
import stat

from tools.test_impact.fixture_inputs import _json, _regular, _relative, _require

RESOURCE_ID = 'b243-remaining3-fixture-bound-v1'
MANIFEST_SHA256 = '3a068de66eea198421897895dce1f00d33772d903a391757e65898bf896ca4a4'
RESOURCE_PATH = Path('tools/test_impact/fixtures/remaining3')
READONLY_ROOT = Path('/source')/RESOURCE_PATH
NATIVE_IDS = (
    'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_sporting_life_race_118984_preserves_distance_units',
    'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_empty_event_distance_uses_real_parsed_metadata_with_original_units',
    'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_real_validated_candidate_packages_with_plan_inventory_identity',
)
SMOKES = ('smoke-japan-50556', 'smoke-united_kingdom-56980',
          'smoke-united_states-70844', 'smoke-hong_kong-49451')


def _canonical(value):
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _validate_discovery(smoke, refs, event, request, identity):
    _require(request['source_provider'] == identity['detail_provider']
             and request['source_url'] == identity['detail_url']
             and str(request['target_id']) == identity['target_id']
             and request['target_sha256'] == identity['target_sha256'],
             'remaining fragment/source identity mismatch')
    calendar = refs['calendar_discovery']
    _require(calendar['edition_year'] == request['year'] == int(event['year']) == identity['year']
             and calendar['local_date'] == request['local_date'] == identity['local_date'],
             'remaining calendar date/year mismatch')
    if smoke in ('smoke-japan-50556', 'smoke-united_states-70844'):
        detail = refs['detail_discovery']
        result = detail['urls']['result_url']
        _require(identity['discovery_schema'] == 'detail_and_calendar'
                 and detail['adapter_key'] == result['source_provider'] == identity['detail_provider']
                 and result['url'] == identity['detail_url']
                 and calendar['source_provider'] == identity['calendar_provider']
                 and calendar['source_url'] == identity['calendar_url']
                 and calendar['source_authority'] == identity['calendar_authority'],
                 'remaining JP/US discovery mismatch')
    elif smoke in ('smoke-united_kingdom-56980', 'smoke-hong_kong-49451'):
        # UK BHA calendar URL/provider differs from Sporting Life detail; no staged detail field is required.
        _require(identity['discovery_schema'] == 'calendar_only'
                 and calendar['calendar_source_provider'] == identity['calendar_provider']
                 and calendar['calendar_source_url'] == identity['calendar_url']
                 and calendar['calendar_source_authority'] == identity['calendar_authority'],
                 'remaining UK/HK calendar discovery mismatch')
    else:
        raise ValueError('fixture inputs: unadmitted remaining smoke')


def resource_environment(source_root):
    """仅由主准入器在 envclear/source/profile/exact3 验证后调用。"""
    root = _regular(source_root, str(RESOURCE_PATH/'manifest.json')).parent
    raw = (root/'manifest.json').read_bytes()
    _require(len(raw) <= 32768 and hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256,
             'remaining fixed manifest mismatch')
    manifest = _json(raw)
    _require(manifest['schema'] == 1 and manifest['id'] == RESOURCE_ID
             and manifest['native_ids'] == list(NATIVE_IDS)
             and len(manifest['files']) == 26 and manifest['view_file_count'] == 21
             and manifest['provenance_file_count'] == 5
             and manifest['readonly_root'] == str(READONLY_ROOT)
             and len(manifest['descriptors']) == 4
             and set(manifest['source_bindings']) == set(SMOKES), 'remaining schema mismatch')
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
            _require(stat.S_ISDIR(path.lstat().st_mode), 'remaining symlink or non-directory')
            actual_dirs.add(str(path.relative_to(root)))
        for name in names:
            path = Path(directory)/name
            _require(stat.S_ISREG(path.lstat().st_mode), 'remaining symlink or non-regular file')
            actual_files.add(str(path.relative_to(root)))
    _require(actual_files == expected_files and actual_dirs == expected_dirs,
             'remaining missing or extra members')
    data = {}
    for name, identity in files.items():
        path = _regular(root, name)
        _require(path.stat().st_size == identity['bytes'], 'remaining size mismatch')
        body = path.read_bytes()
        _require(len(body) == identity['bytes'] and hashlib.sha256(body).hexdigest() == identity['sha256'],
                 'remaining hash mismatch')
        data[name] = body
    plan_sha = hashlib.sha256(data[manifest['plan']]).hexdigest()
    for record in manifest['descriptors']:
        original = _json(data[record['original']])
        view = _json(data[record['view']])
        _require(hashlib.sha256(data[record['original']]).hexdigest() == record['original_raw_sha256']
                 and _canonical(original) == record['original_canonical_sha256']
                 and hashlib.sha256(data[record['view']]).hexdigest() == record['git_view_raw_sha256']
                 and _canonical(view) == record['git_view_canonical_sha256'],
                 'remaining original/view identity mismatch')
        smoke = original['shard_id']
        events_name = 'smoke/events/'+smoke+'.csv'
        fragment_name = 'smoke/source_fragments/'+smoke+'.json'
        # Fresh JSON object, with only two runtime paths relocated. Historical identity fields stay original.
        expected = _json(data[record['original']])
        expected['adapter_inputs']['events_csv'] = str(READONLY_ROOT/events_name)
        expected['adapter_inputs']['source_fragment'] = str(READONLY_ROOT/fragment_name)
        _require(view == expected, 'remaining relocation changed non-path fields')
        inventory = [i for i in view['identities'] if i['role'] == 'plan']
        _require(len(inventory) == 1 and inventory[0]['sha256'] == plan_sha
                 and inventory[0]['size'] == len(data[manifest['plan']]), 'remaining plan identity mismatch')
        events = list(csv.DictReader(io.StringIO(data[events_name].decode('utf-8-sig'))))
        requests = _json(data[fragment_name])['requests']
        _require(len(events) == len(requests) == len(view['targets']) == 1,
                 'remaining single target required')
        event, request, target = events[0], requests[0], view['targets'][0]
        _require(str(event['target_id']) == str(request['target_id']) == str(target['target_id'])
                 and event['target_sha256'] == request['target_sha256'] == target['target_sha256'],
                 'remaining target identity mismatch')
        for role, name in (('events_csv', events_name), ('source_fragment', fragment_name)):
            identities = [i for i in view['identities'] if i['role'] == role]
            _require(len(identities) == 1 and identities[0]['sha256'] == files[name]['sha256']
                     and identities[0]['size'] == files[name]['bytes'], 'remaining adapter input identity mismatch')
        refs = _json(event['source_refs'])
        _validate_discovery(smoke, refs, event, request, manifest['source_bindings'][smoke])
        _require(smoke in SMOKES, 'unadmitted remaining smoke')
        cache_name = 'smoke/run/'+smoke+'/source-cache/source_cache_manifest.json'
        identities = list(_json(data[cache_name])['files'].values())
        _require(len(identities) == 1, 'remaining single cache identity required')
        identity = identities[0]
        body_name = str(_relative(cache_name).parent/_relative(identity['path']))
        _require(body_name in files and identity['sha256'] == files[body_name]['sha256']
                 and int(identity['size']) == files[body_name]['bytes']
                 and identity['source_url'] == request['source_url'], 'remaining cache identity mismatch')
        if smoke == 'smoke-hong_kong-49451':
            # Preserve the real original validation object. Only the native may generate its temporary package.
            candidates = [_json(line) for line in data['smoke/run/'+smoke+'/validated-candidates.jsonl'].splitlines() if line.strip()]
            _require(len(candidates) == 1, 'remaining HK single original candidate required')
            candidate = candidates[0]
            _require(str(candidate['target_id']) == str(target['target_id'])
                     and candidate['target_sha256'] == target['target_sha256']
                     and str(candidate['year']) == event['year'] and candidate['slug'] == event['slug']
                     and candidate['source_url'] == request['source_url']
                     and candidate['validation']['status'] == 'complete'
                     and str(candidate['validation']['target_id']) == str(target['target_id'])
                     and candidate['validation']['event']['source_url'] == request['source_url'],
                     'remaining HK original candidate identity mismatch')
    return {'HISTORICAL_DETAIL_DISTANCE_CACHE_RUN_ROOT': str(root/'smoke/run')}

"""限定显式 native 集合的固定缓存准入；仅使用标准库，不导入应用或测试。"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

RESOURCE_ID = 'b239-primary3-v1'
SECONDARY_RESOURCE_ID = 'b243-secondary2-v1'
REMAINING_RESOURCE_ID = 'b243-remaining3-fixture-bound-v1'
MANIFEST_SHA256 = 'b169ea447a8f6dbc00bb5123df24fe9de50d5da25652eb0329ba5698b5d1ebf9'
RESOURCE_PATH = Path('tools/test_impact/fixtures/primary3')
NATIVE_IDS = (
    'stable.test_historical_race_detail_direct_urls.HistoricalRaceDetailDirectUrlTests.test_sporting_life_real_cache_preserves_structured_non_finish_statuses',
    'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_jra_2005_legacy_page_preserves_distance_unit',
    'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_equibase_yearbook_result_preserves_distance_unit',
)
ENVIRONMENT = {
    'SPORTING_LIFE_REAL_CACHE_RUN_ROOT': 'uk-status',
    'HISTORICAL_DETAIL_DISTANCE_CACHE_RUN_ROOT': 'smoke/run',
}


def _require(condition, message):
    if not condition:
        raise ValueError('fixture inputs: '+message)


def _exact_ids(ids, admitted=NATIVE_IDS):
    _require(type(ids) is list and all(type(i) is str for i in ids), 'native ID list required')
    _require(len(ids) == len(admitted) and set(ids) == set(admitted), 'exact admitted unique native IDs required')


def validate_selection(plan, *, collecting=False):
    """收集前后与执行时使用同一准入合同；默认计划不启用资源。"""
    if 'fixture_inputs' not in plan:
        return
    control = plan['fixture_inputs']
    _require(type(control) is dict and set(control) == {
        'id', 'manifest_sha256', 'source_sha', 'source_tree'}, 'unexpected control fields')
    admitted, manifest_sha = NATIVE_IDS, MANIFEST_SHA256
    if control['id'] == SECONDARY_RESOURCE_ID:
        from tools.test_impact import fixture_inputs_secondary as secondary
        admitted, manifest_sha = secondary.NATIVE_IDS, secondary.MANIFEST_SHA256
    elif control['id'] == REMAINING_RESOURCE_ID:
        from tools.test_impact import fixture_inputs_remaining as remaining
        admitted, manifest_sha = remaining.NATIVE_IDS, remaining.MANIFEST_SHA256
    _require(control['id'] in (RESOURCE_ID, SECONDARY_RESOURCE_ID, REMAINING_RESOURCE_ID)
             and control['manifest_sha256'] == manifest_sha, 'resource identity mismatch')
    count = len(admitted)
    for field, source_field in (('source_sha', 'test_sha'), ('source_tree', 'test_tree')):
        value = control[field]
        _require(type(value) is str and re.fullmatch(r'[0-9a-f]{40}', value) is not None
                 and value == plan.get(source_field), 'source identity mismatch')
    _require(plan.get('source') == 'git' and plan.get('mode') == 'targeted', 'targeted Git plan required')
    _exact_ids(plan.get('labels'), admitted)
    batches = plan.get('batches', [])
    _require(type(batches) is list, 'batch list required')
    if collecting and not batches:
        _require('count' not in plan or type(plan['count']) is int and plan['count'] in (0, count),
                 'invalid collection count')
        return
    _require(batches and type(plan.get('count')) is int and plan['count'] == count,
             'exact collected natives required')
    ids, keys = [], []
    for batch in batches:
        _require(type(batch) is dict and batch.get('profile') == 'django', 'Django batch required')
        key = batch.get('key')
        _require(type(key) is str and re.fullmatch(r'batch-[0-9]{3}', key) is not None,
                 'invalid batch key')
        _require(type(batch.get('ids')) is list and batch['ids'], 'nonempty batch IDs required')
        ids.extend(batch['ids'])
        keys.append(key)
    _require(len(keys) == len(set(keys)), 'duplicate batch key')
    _exact_ids(ids, admitted)


def _relative(value):
    _require(type(value) is str and value and not value.startswith('/') and '\\' not in value
             and all(p not in ('', '.', '..') for p in value.split('/')), 'unsafe resource path')
    return Path(value)


def _regular(root, relative):
    path = root
    parts = _relative(relative).parts
    for index, part in enumerate(parts):
        path = path/part
        mode = path.lstat().st_mode
        _require(stat.S_ISREG(mode) if index == len(parts)-1 else stat.S_ISDIR(mode),
                 'non-regular resource or symlink')
    return path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('fixture inputs: invalid JSON constant')


def _json(data):
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=_invalid_constant)


def fixture_environment(plan, binding, code_sha, profile, *, collecting=False,
                        inherited_keys=(), source_root=Path('/source')):
    """envclear 后调用；验证全部字节后才返回固定只读路径。"""
    _require(not set(inherited_keys).intersection(ENVIRONMENT)
             and not set(os.environ).intersection(ENVIRONMENT), 'host fixture environment injection')
    validate_selection(plan, collecting=collecting)
    if 'fixture_inputs' not in plan:
        return {}
    _require(profile == 'django', 'Django worker required')
    _require(code_sha == plan['test_sha'] == binding.get('test_sha')
             and plan['test_tree'] == binding.get('test_tree'), 'verified source identity mismatch')
    # Production caller supplies no path from the plan or inherited environment.
    source_root = Path(source_root)
    _require(source_root.is_absolute() and stat.S_ISDIR(source_root.lstat().st_mode),
             'regular absolute source directory required')
    if plan['fixture_inputs']['id'] == SECONDARY_RESOURCE_ID:
        from tools.test_impact.fixture_inputs_secondary import resource_environment
        return resource_environment(source_root)
    if plan['fixture_inputs']['id'] == REMAINING_RESOURCE_ID:
        from tools.test_impact.fixture_inputs_remaining import resource_environment
        return resource_environment(source_root)
    root = _regular(source_root, str(RESOURCE_PATH/'manifest.json')).parent
    raw = (root/'manifest.json').read_bytes()
    _require(len(raw) <= 32768 and hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256,
             'fixed resource manifest mismatch')
    manifest = _json(raw)
    _require(manifest['schema'] == 1 and manifest['id'] == RESOURCE_ID
             and manifest['native_ids'] == list(NATIVE_IDS) and len(manifest['files']) == 10,
             'resource schema mismatch')
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
            _require(stat.S_ISDIR(path.lstat().st_mode), 'symlink or non-directory')
            actual_dirs.add(str(path.relative_to(root)))
        for name in names:
            path = Path(directory)/name
            _require(stat.S_ISREG(path.lstat().st_mode), 'symlink or non-regular file')
            actual_files.add(str(path.relative_to(root)))
    _require(actual_files == expected_files and actual_dirs == expected_dirs,
             'missing or extra resource members')
    bodies = {}
    for name, identity in files.items():
        path = _regular(root, name)
        _require(path.stat().st_size == identity['bytes'], 'resource size mismatch')
        body = path.read_bytes()
        _require(len(body) == identity['bytes'] and hashlib.sha256(body).hexdigest() == identity['sha256'],
                 'resource hash mismatch')
        bodies[name] = body
    for selection in manifest['selections']:
        original = _json(bodies[selection['manifest']])
        identities = list(original['files'].values())
        if selection['single_identity']:
            _require(len(identities) == 1, 'single identity required')
        selected = [i for i in identities if i.get('path') == selection['filename']]
        _require(len(selected) == 1, 'selected identity must be unique')
        identity = selected[0]
        relative = str(_relative(selection['manifest']).parent/_relative(identity['path']))
        _require(relative in files and identity['source_url'] == selection['source_url']
                 and identity['sha256'] == files[relative]['sha256']
                 and int(identity['size']) == files[relative]['bytes'], 'selected identity mismatch')
        # UK manifests remain whole; their other 35 bodies are not dependencies.
    return {key: str(root/relative) for key, relative in ENVIRONMENT.items()}

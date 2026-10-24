"""full-composition-v1 的纯结构合同；不采集、不执行、不认证收据。

调用方须从候选外提供固定 identity/catalog/rules/protected_native_ids。
collection 是原收集结果的显式适配结构，不是现有 plan 的自动升级。
producer.kind/invocation_id/raw_sha256 仅检查结构，不能证明独立性或真实运行。
本模块未挂任何正式路径；check_execution_structure 不替代原 core.verify_results、
候选外 full collect、能力资格、PG/CID/上传与交付核验；formal_gate 固定 NOT_READY。

生命周期策略显式承认跨 route 的类/module setup/teardown 会重复执行；集合守恒
不证明初始化、事务、线程和临时文件的行为等价，须原 owner 后续专项验证。
"""
import copy
import hashlib
import json
import re

SCHEMA = 'full-composition-v1'
LIFECYCLE_POLICY = 'class-lifecycle-per-route-v1'
ROLES = ('ordinary', 'cache_primary3', 'cache_secondary2', 'cache_remaining3',
         'image_singleton', 'root_singleton')
CAPABILITY_ROLES = ('image_singleton', 'root_singleton')
SPECIAL_IDS = {'cache_primary3': ('stable.test_historical_race_detail_direct_urls.HistoricalRaceDetailDirectUrlTests.test_sporting_life_real_cache_preserves_structured_non_finish_statuses',
                    'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_jra_2005_legacy_page_preserves_distance_unit',
                    'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_equibase_yearbook_result_preserves_distance_unit'),
 'cache_secondary2': ('stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_nonempty_event_and_parsed_distance_conflict_becomes_validation_gap',
                      'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_package_rejects_raw_candidate_without_validation_evidence'),
 'cache_remaining3': ('stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_sporting_life_race_118984_preserves_distance_units',
                      'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_empty_event_distance_uses_real_parsed_metadata_with_original_units',
                      'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_real_validated_candidate_packages_with_plan_inventory_identity'),
 'image_singleton': ('stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file',),
 'root_singleton': ('stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace',)}
RESOURCES = {'cache_primary3': ('b239-primary3-v1', 'b169ea447a8f6dbc00bb5123df24fe9de50d5da25652eb0329ba5698b5d1ebf9'),
 'cache_secondary2': ('b243-secondary2-v1',
                      'd564676417d45ed1b49dc08d4877cbde555b537939477f5c11fb070055052e93'),
 'cache_remaining3': ('b243-remaining3-fixture-bound-v1',
                      '3a068de66eea198421897895dce1f00d33772d903a391757e65898bf896ca4a4')}

IDENTITY_FIELDS = frozenset((
    'base_sha', 'head_sha', 'test_sha', 'test_tree', 'run_id', 'run_attempt', 'image_id',
    'catalog_digest', 'rules_digest', 'control_manifest_digest', 'image_supply_policy_digest',
    'capability_subject_pins_digest', 'lifecycle_policy_digest'))
COLLECTION_FIELDS = frozenset(('mode', 'identity', 'labels', 'batches', 'count',
                               'aliases', 'collection_skips', 'producer'))
REPORT_FIELDS = frozenset(('key', 'profile', 'plan_digest', 'run_id', 'run_attempt',
                          'test_tree', 'executed', 'failures', 'errors', 'skips',
                          'expected_failures', 'unexpected_successes', 'lifecycle', 'exit_code'))
REPORT_TELEMETRY_FIELDS = frozenset(('python', 'os', 'isolation', 'postgresql', 'django', 'seconds'))
NAME = re.compile(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*\Z')
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\Z')
BATCH_KEY = re.compile(r'batch-[0-9]{3,}\Z')


class NotReady(ValueError):
    """缺未实现的可信执行/API 或能力证据；不得冒充业务 RED。"""


def _require(condition, message):
    if not condition:
        raise ValueError('full composition: ' + message)


def _keys(value, keys, name):
    _require(type(value) is dict and set(value) == set(keys), name + ' exact fields required')


def _hex(value, size):
    return type(value) is str and re.fullmatch('[0-9a-f]{%d}' % size, value) is not None


def _digest(value):
    # 与旧 core.digest 一致；拒 NaN 等不属于协议的 JSON。
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _names(value, name, *, nonempty=False):
    _require(type(value) is list and (not nonempty or value), name + ' list required')
    _require(all(type(v) is str and NAME.fullmatch(v) for v in value), name + ' qualified names required')
    _require(len(value) == len(set(value)), name + ' duplicate')
    return value


def _identity(identity, catalog, rules):
    _keys(identity, IDENTITY_FIELDS, 'identity')
    for key in ('base_sha', 'head_sha', 'test_sha', 'test_tree'):
        _require(_hex(identity[key], 40), key + ' SHA required')
    for key in IDENTITY_FIELDS - {'base_sha', 'head_sha', 'test_sha', 'test_tree',
                                  'run_id', 'run_attempt', 'image_id'}:
        _require(_hex(identity[key], 64), key + ' digest required')
    _require(type(identity['run_id']) is str and re.fullmatch('[1-9][0-9]*', identity['run_id']), 'run ID required')
    _require(type(identity['run_attempt']) is int and identity['run_attempt'] > 0, 'positive run attempt required')
    _require(type(identity['image_id']) is str and re.fullmatch('sha256:[0-9a-f]{64}', identity['image_id']), 'immutable image required')
    _require(type(catalog) is dict and type(rules) is dict, 'catalog/rules objects required')
    _require(identity['catalog_digest'] == _digest(catalog) and identity['rules_digest'] == _digest(rules),
             'catalog/rules digest mismatch')


def _catalog_labels(catalog):
    _require(type(catalog.get('schema_version')) is int and catalog['schema_version'] == 1, 'catalog schema')
    domains = catalog.get('domains')
    _require(type(domains) is dict and 'core' in domains, 'complete catalog domains required')
    labels = set()
    for name, values in domains.items():
        _require(type(name) is str and TOKEN.fullmatch(name), 'domain name')
        labels.update(_names(values, 'catalog domain labels'))
    _require(labels, 'empty full catalog')
    profiles = catalog.get('profiles')
    _require(type(profiles) is dict and profiles, 'catalog profiles required')
    for module, profile in profiles.items():
        _require(type(module) is str and NAME.fullmatch(module), 'profile module')
        _require(type(profile) is str and TOKEN.fullmatch(profile), 'profile name')
    _names(catalog.get('dedicated_batch_modules', []), 'dedicated modules')
    _require(type(catalog.get('allowed_skips', {})) is dict, 'skip policies object required')
    return sorted(labels)


def _profile(ident, catalog):
    owners = [p for module, p in catalog['profiles'].items() if ident.startswith(module + '.')]
    _require(len(owners) == 1, 'unowned or ambiguous profile: ' + ident)
    return owners[0]


def _shard(records, catalog):
    """旧 core.shard_tests(limit=200) 的纯数据规则；不修改或导入旧执行器。

    专项测试以旧函数作独立兼容性 oracle；正式适配仍须原 core 逐 child 核验。
    """
    classes = {}
    dedicated = set()
    for item in records:
        key = (item['profile'], item['id'].rsplit('.', 1)[0])
        classes.setdefault(key, []).append(item['id'])
        if any(item['id'].startswith(m + '.') for m in catalog.get('dedicated_batch_modules', [])):
            dedicated.add(key)
    batches, previous_dedicated = [], False
    for key, ids in sorted(classes.items()):
        _require(len(ids) <= 200, 'class exceeds 200: ' + key[1])
        separate = key in dedicated
        if (not batches or previous_dedicated or separate or batches[-1]['profile'] != key[0]
                or len(batches[-1]['ids']) + len(ids) > 200):
            batches.append(dict(key='batch-%03d' % len(batches), profile=key[0], ids=[]))
        batches[-1]['ids'].extend(sorted(ids))
        previous_dedicated = separate
    return batches


def _collection(value, identity, catalog, labels, kind):
    _keys(value, COLLECTION_FIELDS, 'collection')
    _require(value['mode'] == 'full' and _digest(value['identity']) == _digest(identity), 'collection mode/identity mismatch')
    _require(_names(value['labels'], 'full labels', nonempty=True) == labels, 'not complete sorted catalog labels')
    _keys(value['producer'], ('kind', 'invocation_id', 'raw_sha256'), 'collection producer')
    producer = value['producer']
    _require(producer['kind'] == kind, 'collection producer origin mismatch')
    _require(type(producer['invocation_id']) is str and TOKEN.fullmatch(producer['invocation_id']), 'collector invocation')
    _require(_hex(producer['raw_sha256'], 64), 'raw collection hash required')
    _require(type(value['count']) is int and value['count'] > 0, 'native count required')
    _require(type(value['batches']) is list and value['batches'], 'full batches required')
    universe, seen, keys = [], set(), set()
    for batch in value['batches']:
        _keys(batch, ('key', 'profile', 'ids'), 'collection batch')
        _require(type(batch['key']) is str and BATCH_KEY.fullmatch(batch['key']) and batch['key'] not in keys,
                 'invalid/duplicate batch key')
        keys.add(batch['key'])
        for ident in _names(batch['ids'], 'batch IDs', nonempty=True):
            _require(ident not in seen, 'duplicate native ID')
            _require(any(ident == label or ident.startswith(label + '.') for label in labels), 'ID outside full labels')
            _require(batch['profile'] == _profile(ident, catalog), 'native profile mismatch')
            seen.add(ident)
            universe.append(dict(id=ident, profile=batch['profile']))
    universe.sort(key=lambda item: item['id'])
    _require(len(universe) == value['count'], 'full collection count mismatch')
    _require(value['batches'] == _shard(universe, catalog), 'nonstandard full batches')
    _require(type(value['aliases']) is list and type(value['collection_skips']) is list, 'collection metadata lists required')
    alias_pairs = set()
    for alias in value['aliases']:
        _keys(alias, ('id', 'label'), 'alias')
        _require(type(alias['id']) is str and type(alias['label']) is str, 'alias strings required')
        pair = (alias['id'], alias['label'])
        _require(pair not in alias_pairs and alias['id'] in seen and alias['label'] in labels, 'unknown/duplicate alias')
        _require(alias['id'] == alias['label'] or alias['id'].startswith(alias['label'] + '.'), 'alias ownership mismatch')
        alias_pairs.add(pair)
    skip_ids = set()
    for skip in value['collection_skips']:
        _keys(skip, ('id', 'reason'), 'declared collection skip')
        _require(type(skip['id']) is str and skip['id'] in seen and skip['id'] not in skip_ids
                 and type(skip['reason']) is str, 'unknown/duplicate declared skip')
        skip_ids.add(skip['id'])
    return universe


def compile_parent(identity, catalog, rules, candidate, independent, protected_native_ids):
    """重建六路不可变规格的 JSON 值；不读取文件、不启动收集、不认证外部输入。

    protected_native_ids 必须来自受信旧清单及变化审查，不能由候选新 N 自行替代。
    两个完整收集必须原始独立产生；这里只能拒缺失/布尔/同 invocation 等结构冒充。
    """
    _identity(identity, catalog, rules)
    labels = _catalog_labels(catalog)
    universe = _collection(candidate, identity, catalog, labels, 'candidate')
    other = _collection(independent, identity, catalog, labels, 'candidate-external')
    _require(candidate['producer']['invocation_id'] != independent['producer']['invocation_id'], 'same collector invocation')
    for field in ('labels', 'batches', 'count', 'aliases', 'collection_skips'):
        _require(candidate[field] == independent[field], 'independent full collection mismatch: ' + field)
    _require(universe == other, 'independent universe mismatch')
    protected = _names(protected_native_ids, 'trusted protected IDs', nonempty=True)
    ids = {item['id'] for item in universe}
    _require(set(protected) <= ids, 'protected native ID removed')
    special = {ident: role for role, values in SPECIAL_IDS.items() for ident in values}
    _require(len(special) == 10 and set(special) <= ids, 'required special native IDs missing')
    for item in universe:
        if item['id'] in special:
            _require(item['profile'] == 'django', 'special native profile changed')
    specs, accounted = [], set()
    for role in ROLES:
        records = [item for item in universe if special.get(item['id'], 'ordinary') == role]
        routed = [item['id'] for item in records]
        _require(not accounted.intersection(routed), 'route intersection')
        accounted.update(routed)
        plan = dict(copy.deepcopy(identity), source='git', mode='expanded' if len(records) > 400 else 'targeted',
                    labels=routed, batches=_shard(records, catalog), count=len(records), aliases=[],
                    allowed_skips=copy.deepcopy(catalog.get('allowed_skips', {})))
        if role in RESOURCES:
            resource, manifest = RESOURCES[role]
            plan['fixture_inputs'] = dict(id=resource, manifest_sha256=manifest,
                                          source_sha=identity['test_sha'], source_tree=identity['test_tree'])
        if role in CAPABILITY_ROLES:
            plan['capability_role'] = role
        specs.append(dict(role=role, plan=plan))
    _require(accounted == ids and sum(s['plan']['count'] for s in specs) == len(universe), 'route disjoint union mismatch')
    return dict(schema_version=SCHEMA, mode='full', identity=copy.deepcopy(identity),
                selection_labels=labels, collections=dict(candidate=copy.deepcopy(candidate), independent=copy.deepcopy(independent)),
                universe=universe, count=len(universe), protected_native_ids=sorted(protected),
                allowed_skips=copy.deepcopy(catalog.get('allowed_skips', {})),
                lifecycle_policy=LIFECYCLE_POLICY, child_specs=specs)


def derive_children(parent, *, identity, catalog, rules, protected_native_ids):
    """使用调用方受信上下文重建 parent，再生成附 parent 摘要的原语义 child plans。"""
    _require(type(parent) is dict and type(parent.get('collections')) is dict, 'parent collections required')
    _keys(parent['collections'], ('candidate', 'independent'), 'parent collections')
    rebuilt = compile_parent(identity, catalog, rules, parent['collections']['candidate'],
                             parent['collections']['independent'], protected_native_ids)
    _require(_digest(parent) == _digest(rebuilt), 'parent spec mismatch')
    parent_digest = _digest(rebuilt)
    children = []
    for spec in rebuilt['child_specs']:
        plan = copy.deepcopy(spec['plan'])
        plan['parent_full_digest'] = parent_digest
        children.append(dict(role=spec['role'], plan=plan, plan_digest=_digest(plan)))
    return children


def batch_namespace(role, child_digest, batch_key):
    """固定三元命名空间；只返回路径，不创建/扫描文件或容器。"""
    _require(type(role) is str and role in ROLES, 'unknown role')
    _require(_hex(child_digest, 64), 'child digest required')
    _require(type(batch_key) is str and BATCH_KEY.fullmatch(batch_key), 'invalid raw batch key')
    return 'roles/%s/%s/%s.json' % (role, child_digest, batch_key)


def _capabilities(values):
    _require(type(values) is list, 'capabilities list required')
    roles = set()
    for value in values:
        _keys(value, ('role', 'status'), 'capability structure')
        _require(type(value['role']) is str and value['role'] in CAPABILITY_ROLES and value['role'] not in roles,
                 'unknown/duplicate capability role')
        _require(value['status'] in ('READY', 'BLOCKED', 'NOT_READY'), 'unknown capability status')
        roles.add(value['role'])
    if roles != set(CAPABILITY_ROLES) or any(v['status'] != 'READY' for v in values):
        raise NotReady('capability BLOCKED/NOT_READY/missing; no formal GREEN')
    # READY 也只是结构输入；真实资格验证尚无 API，formal_gate 仍拒绝。


def check_execution_structure(parent, children, reports, capabilities, *, identity, catalog, rules, protected_native_ids):
    """核验 raw report 的集合/绑定/零 skip 结构。只返回 STRUCTURE_VALID_GATE_NOT_READY。

    不接受 passed=true 等摘要代替原报告；不重写其 key/plan_digest/mode。
    原 core.verify_results 和全部真实运行证据须由后续受审适配器独立调用/核验。
    """
    expected_children = derive_children(parent, identity=identity, catalog=catalog, rules=rules,
                                         protected_native_ids=protected_native_ids)
    _require(type(children) is list and len(children) == len(ROLES), 'missing/duplicate child')
    by_role = {}
    for child in children:
        _keys(child, ('role', 'plan', 'plan_digest'), 'child')
        role = child['role']
        _require(type(role) is str and role in ROLES and role not in by_role, 'unknown/duplicate child role')
        by_role[role] = child
    _require(_digest([by_role[r] for r in ROLES]) == _digest(expected_children), 'derived child spec/digest mismatch')
    _capabilities(capabilities)
    expected = {}
    for child in expected_children:
        for batch in child['plan']['batches']:
            key = (child['role'], child['plan_digest'], batch['key'])
            batch_namespace(*key)
            _require(key not in expected, 'namespace collision')
            expected[key] = (child['plan'], batch)
    _require(type(reports) is list and len(reports) == len(expected), 'missing/duplicate/extra reports')
    seen, executed = set(), []
    for envelope in reports:
        _keys(envelope, ('role', 'child_plan_digest', 'report'), 'report envelope')
        report = envelope['report']
        _require(type(report) is dict and REPORT_FIELDS <= set(report)
                 and set(report) <= REPORT_FIELDS | REPORT_TELEMETRY_FIELDS, 'raw report fields mismatch')
        # 保留原 worker 的 telemetry；它不提供资格或生命周期的可信证明。
        _digest(report)
        key = (envelope['role'], envelope['child_plan_digest'], report['key'])
        batch_namespace(*key)
        _require(key in expected and key not in seen, 'unowned/duplicate raw report')
        seen.add(key)
        plan, batch = expected[key]
        _require(report['plan_digest'] == key[1] and report['profile'] == batch['profile'], 'raw plan/profile mismatch')
        for field in ('run_id', 'run_attempt', 'test_tree'):
            _require(type(report[field]) is type(plan[field]) and report[field] == plan[field], 'raw identity mismatch: ' + field)
        actual = _names(report['executed'], 'executed IDs', nonempty=True)
        _require(set(actual) == set(batch['ids']), 'raw execution set mismatch')
        for field in ('failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes'):
            _require(type(report[field]) is list and not report[field], 'nonzero raw outcome: ' + field)
        _require(type(report['exit_code']) is int and report['exit_code'] == 0 and report['lifecycle'] == 'complete',
                 'failed/unknown raw lifecycle')
        executed.extend(actual)
    _require(seen == set(expected) and len(executed) == len(set(executed)) == parent['count']
             and set(executed) == {r['id'] for r in parent['universe']}, 'executed disjoint union mismatch')
    return dict(status='STRUCTURE_VALID_GATE_NOT_READY', count=parent['count'], skipped_count=0)


def formal_gate(*args, **kwargs):
    """没有真实独立 collector/core/capability/lifecycle/delivery API 时永不出正式 GREEN。"""
    raise NotReady('trusted independent collect, original per-child core verification, capability qualification, '
                   'lifecycle/owned cleanup/upload/delivery adapters NOT_READY; structure is not formal GREEN')

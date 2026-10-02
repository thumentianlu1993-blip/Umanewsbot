"""测试范围与证据的纯数据合同；不导入应用。"""
import ast
import fnmatch
import hashlib
import json
from pathlib import PurePosixPath


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def safe_path(path):
    if not path or path.startswith('/') or '..' in PurePosixPath(path).parts or '\\' in path:
        raise ValueError(f'unsafe path: {path!r}')
    return path


def symbols(source):
    tree = ast.parse(source or '')
    named, initialization = {}, []
    for node in tree.body:
        value = ast.dump(node, include_attributes=False)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in named:
                raise ValueError(f'duplicate top-level symbol: {node.name}')
            named[node.name] = value
        else:
            initialization.append(value)
    return named, initialization


def validate_catalog(catalog):
    if catalog.get('schema_version') != 1:
        raise ValueError('unsupported catalog schema')
    domains = catalog['domains']
    if 'core' not in domains:
        raise ValueError('catalog missing core')
    for name, labels in domains.items():
        if len(labels) != len(set(labels)):
            raise ValueError(f'duplicate label: {name}')
    for name, deps in catalog.get('dependencies', {}).items():
        if name not in domains or set(deps) - domains.keys():
            raise ValueError(f'unknown dependency: {name}')
    for path, entry in catalog.get('tests', {}).items():
        safe_path(path)
        if not entry['domains'] or set(entry['domains']) - domains.keys():
            raise ValueError(f'unknown test domain: {path}')


def select_changes(changes, rules, catalog):
    validate_catalog(catalog)
    if not changes:
        raise ValueError('empty diff: no evidence can be inferred')
    domains, reasons, unknown = set(), [], []
    full = False
    for change in changes:
        path = safe_path(change['path'])
        selected = set()
        if matches(path, rules['high_risk']):
            full = True
            reasons.append({'path': path, 'reason': 'shared/high-risk'})
            continue
        if path in rules.get('symbols', {}):
            mapping = rules['symbols'][path]
            try:
                before, init_before = symbols(change.get('before', ''))
                after, init_after = symbols(change.get('after', ''))
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f'unmapped AST: {path}: {exc}') from exc
            changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
            missing = changed - mapping.keys()
            if missing:
                unknown.append(f'{path}:{",".join(sorted(missing))}')
            for name in changed & mapping.keys():
                selected.update(mapping[name])
            if init_before != init_after:
                if path in rules.get('module_initialization_full', []):
                    full = True
                for values in mapping.values():
                    selected.update(values)
            # 注释/格式变化也保留该文件的已登记领域，不能空选。
            if not changed and init_before == init_after:
                for values in mapping.values():
                    selected.update(values)
        elif path in catalog.get('tests', {}):
            selected.update(catalog['tests'][path]['domains'])
        else:
            for pattern, values in rules.get('paths', {}).items():
                if matches(path, [pattern]):
                    selected.update(values)
            if not selected:
                if matches(path, rules['docs']):
                    reasons.append({'path': path, 'reason': 'documentation'})
                    continue
                unknown.append(path)
        domains.update(selected)
        reasons.append({'path': path, 'reason': 'mapped', 'domains': sorted(selected)})
    # 即使同时有 high-risk 文件，也不隐藏未登记路径。
    if unknown:
        raise ValueError('unmapped: ' + ', '.join(sorted(unknown)))
    if domains - catalog['domains'].keys():
        raise ValueError('unknown domain: ' + ', '.join(sorted(domains - catalog['domains'].keys())))
    if full:
        domains = set(catalog['domains'])
    elif domains:
        domains.add('core')
    pending = list(domains)
    while pending:
        for dep in catalog.get('dependencies', {}).get(pending.pop(), []):
            if dep not in domains:
                domains.add(dep)
                pending.append(dep)
    labels = sorted({label for name in domains for label in catalog['domains'][name]})
    return {'mode': 'full' if full else 'targeted' if domains else 'docs-only',
            'domains': sorted(domains), 'labels': labels, 'reasons': reasons}


def union_selection(old, new):
    rank = {'docs-only': 0, 'targeted': 1, 'expanded': 2, 'full': 3}
    return {'mode': max((old['mode'], new['mode']), key=rank.get),
            'domains': sorted(set(old['domains']) | set(new['domains'])),
            'labels': sorted(set(old['labels']) | set(new['labels'])),
            'reasons': old['reasons'] + new['reasons']}


def shard_tests(tests, limit=200):
    """输入为 canonical ID/profile，按整类打包，拒绝不明确的所有权。"""
    classes, seen = {}, set()
    for test in tests:
        key = test['id']
        if key in seen:
            raise ValueError(f'duplicate test ID: {key}')
        seen.add(key)
        classes.setdefault((test['profile'], key.rsplit('.', 1)[0]), []).append(key)
    batches = []
    dedicated = {(t['profile'], t['id'].rsplit('.',1)[0]) for t in tests if t.get('dedicated_batch')}
    previous_dedicated = False
    for (profile, cls), ids in sorted(classes.items()):
        if len(ids) > limit:
            raise ValueError(f'class exceeds {limit}: {cls}')
        separate = (profile, cls) in dedicated
        if not batches or previous_dedicated or separate or batches[-1]['profile'] != profile or len(batches[-1]['ids']) + len(ids) > limit:
            batches.append({'key': f'batch-{len(batches):03}', 'profile': profile, 'ids': []})
        batches[-1]['ids'].extend(sorted(ids))
        previous_dedicated = separate
    return batches


def verify_results(plan, reports):
    """任何遗漏、意外跳过、收尾失败都不能被一个 passed=true 覆盖。"""
    expected = {b['key']: b for b in plan['batches']}
    if len(reports) != len(expected) or {r['key'] for r in reports} != set(expected):
        raise ValueError('missing/duplicate/unexpected batch')
    for report in reports:
        batch = expected[report['key']]
        if report['plan_digest'] != digest(plan) or report['profile'] != batch['profile']:
            raise ValueError('plan/profile mismatch')
        for field in ('run_id', 'run_attempt', 'test_tree'):
            if report[field] != plan[field]:
                raise ValueError(f'identity mismatch: {field}')
        ids = report['executed']
        if len(ids) != len(set(ids)) or set(ids) != set(batch['ids']):
            raise ValueError('execution set mismatch')
        if report['exit_code'] != 0 or report['lifecycle'] != 'complete' or report['failures'] or report['errors'] or report['unexpected_successes'] or report['expected_failures']:
            raise ValueError('failed test or lifecycle')
        from datetime import date
        allowed = plan.get('allowed_skips', {})
        for item in report['skips']:
            policy = allowed.get(item['id'])
            if not policy or policy['profile'] != batch['profile'] or policy['reason'] != item['reason'] or date.fromisoformat(policy['review_by']) < date.today():
                raise ValueError('unexpected/expired skip')
    skipped = sum(len(r['skips']) for r in reports)
    return {'status': 'passed', 'skipped_count': skipped, 'mode': plan['mode'], 'count': sum(len(b['ids']) for b in expected.values()),
            'plan_digest': digest(plan), 'run_id': plan['run_id'], 'run_attempt': plan['run_attempt'], 'test_tree': plan['test_tree']}

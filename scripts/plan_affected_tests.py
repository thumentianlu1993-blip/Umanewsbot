#!/usr/bin/env python3
"""按固定 Git 对象或本地工作区生成选测计划（不执行测试）。"""
import argparse
import ast
import copy
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.test_impact.core import digest, select_changes, union_selection
from tools.test_impact.git_input import inputs, read_json, git

RULES = 'tools/test_impact/rules.json'
CATALOG = 'tools/test_impact/catalog.json'


def create_plan(root, base, head, test, local=False, full_reason=None, bootstrap=False):
    data = inputs(root, base, head, test, local)
    rules, catalog = [(json.loads((root / p).read_text()) if local else read_json(root, test, p)) for p in (RULES, CATALOG)]
    missing = [p for p in data['paths'] if ((p.startswith('server/stable/') and (Path(p).name.startswith('test') and p.endswith('.py'))) or p.startswith('scripts/tests/test_') or (p.startswith('runtime/research/test_') and p.endswith('.py'))) and p not in catalog['tests']]
    if missing:
        raise ValueError('catalog drift: ' + ', '.join(missing))
    old_rules, old_catalog = (rules, catalog) if bootstrap else [read_json(root, base, p) for p in (RULES, CATALOG)]
    removed = [c for c in data['changes'] if c['status']=='deleted' and c['path'] in old_catalog['tests']]
    removed_labels = {old_catalog['tests'][c['path']]['label'] for c in removed}
    deleted_ids = []
    for c in removed:
        module = old_catalog['tests'][c['path']]['label']
        for cls in ast.parse(c['before']).body:
            if isinstance(cls, ast.ClassDef):
                deleted_ids.extend(module+'.'+cls.name+'.'+m.name for m in cls.body
                                   if isinstance(m, ast.FunctionDef) and m.name.startswith('test'))
    # 删除文件仍按旧领域分析；移除后不再加载不存在的模块。
    selection_catalog = copy.deepcopy(catalog)
    for c in removed:
        entry=old_catalog['tests'][c['path']]
        selection_catalog['tests'][c['path']]=entry
        for domain in entry['domains']:
            selection_catalog['domains'].setdefault(domain, old_catalog['domains'][domain])
    def full_selection(value, reason):
        return {'mode':'full','domains':sorted(value['domains']),
                'labels':sorted({v for values in value['domains'].values() for v in values}),
                'reasons':[{'reason':reason}]}
    if full_reason:
        chosen = full_selection(catalog, full_reason)
    else:
        # 先验证候选所有路径都已登记，规则变更也不能掩盖真正未知的文件。
        chosen = select_changes(data['changes'], rules, selection_catalog)
    if not bootstrap:
        if rules != old_rules or catalog != old_catalog:
            chosen = union_selection(chosen, full_selection(old_catalog, 'rules/catalog changed: preserve old coverage'))
            chosen = union_selection(chosen, full_selection(catalog, 'rules/catalog changed: validate new coverage'))
        elif data['changes'] and not full_reason:
            from tools.test_impact.git_input import files
            existing = files(root, base)
            prior_changes = [c for c in data['changes'] if c['path'] in existing]
            if prior_changes:
                chosen = union_selection(select_changes(prior_changes, old_rules, old_catalog), chosen)
    chosen['labels'] = [v for v in chosen['labels'] if not any(v==label or v.startswith(label+'.') for label in removed_labels)]
    hashes = {p: digest(json.loads((root / p).read_text()) if local else read_json(root, test, p)) for p in (RULES, CATALOG)}
    return {**{k: v for k, v in data.items() if k not in ('changes', 'paths')}, **chosen,
            'schema_version': 1, 'hashes': hashes, 'bootstrap': bootstrap,
            'changed_paths': [{k:v for k,v in c.items() if k not in ('before','after')} for c in data['changes']],
            'deleted_test_modules': sorted(removed_labels), 'deleted_declared_test_ids': sorted(deleted_ids), 'allowed_skips': catalog.get('allowed_skips', {}),
            'run_id': os.environ.get('GITHUB_RUN_ID', 'local'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT', 'local')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head')
    parser.add_argument('--test')
    parser.add_argument('--local', action='store_true')
    parser.add_argument('--full-reason')
    parser.add_argument('--bootstrap', action='store_true', help='首个引导版本仅诊断，不构成交付收据')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    head = args.head or git(ROOT, 'rev-parse', 'HEAD').decode().strip()
    plan = create_plan(ROOT, args.base, head, args.test or head, args.local, args.full_reason, args.bootstrap)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'mode': plan['mode'], 'domain_count': len(plan['domains']), 'labels': len(plan['labels']), 'plan_digest': digest(plan)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

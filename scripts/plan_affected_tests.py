#!/usr/bin/env python3
"""按固定 Git 对象或本地工作区生成选测计划（不执行测试）。"""
import argparse
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
    if full_reason:
        chosen = {'mode': 'full', 'domains': sorted(catalog['domains']),
                  'labels': sorted({v for values in catalog['domains'].values() for v in values}),
                  'reasons': [{'reason': full_reason}]}
    else:
        chosen = select_changes(data['changes'], rules, catalog)
    old_catalog = catalog
    if not bootstrap:
        old_rules, old_catalog = [read_json(root, base, p) for p in (RULES, CATALOG)]
        if data['changes']:
            from tools.test_impact.git_input import files
            existing = files(root, base)
            prior_changes = [c for c in data['changes'] if c['path'] in existing]
            if prior_changes:
                old = select_changes(prior_changes, old_rules, old_catalog)
                chosen = union_selection(old, chosen)
    removed = [p for p in data['changes'] if p['status'] == 'deleted' and p['path'] in old_catalog['tests']]
    # 删除模块仍保留旧领域；实际不存在的模块只从执行清单移除并明确登记。
    removed_labels = {old_catalog['tests'][p['path']]['label'] for p in removed}
    chosen['labels'] = [v for v in chosen['labels'] if v not in removed_labels]
    hashes = {p: digest(json.loads((root / p).read_text()) if local else read_json(root, test, p)) for p in (RULES, CATALOG)}
    return {**{k: v for k, v in data.items() if k not in ('changes', 'paths')}, **chosen,
            'schema_version': 1, 'hashes': hashes, 'bootstrap': bootstrap,
            'changed_paths': [{k:v for k,v in c.items() if k not in ('before','after')} for c in data['changes']],
            'deleted_test_modules': sorted(removed_labels), 'allowed_skips': catalog.get('allowed_skips', {}),
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

#!/usr/bin/env python3
"""CI 固定身份、静态验证和受控诊断入口。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from plan_affected_tests import create_plan
from tools.test_impact.core import digest
from tools.test_impact.git_input import git, files


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--base',required=True);p.add_argument('--head',required=True);p.add_argument('--test',required=True)
    p.add_argument('--scope',choices=['affected','toolchain','release','full','inventory'],default='affected')
    p.add_argument('--reason',default='');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.scope!='affected' and not a.reason.strip():raise ValueError('manual scope requires reason')
    bootstrap='tools/test_impact/rules.json' not in files(ROOT,a.base)
    plan=create_plan(ROOT,a.base,a.head,a.test,full_reason=a.reason if a.scope in ('full','inventory') else None,bootstrap=bootstrap)
    if a.scope in ('toolchain','release'):
        catalog=json.loads((ROOT/'tools/test_impact/catalog.json').read_text())
        domains=['infrastructure','core','research_contracts','p0_bridge'] if a.scope=='toolchain' else ['release']
        plan.update(mode='validation-only',domains=domains,labels=sorted({label for d in domains for label in catalog['domains'][d]}),validation_scope=a.scope)
    if a.scope=='inventory': plan.update(mode='validation-only',validation_scope='inventory')
    controlled=[path for path in files(ROOT,a.test) if path.startswith(('tools/test_impact/','deploy/test-impact/')) or path in ('requirements.txt','scripts/plan_affected_tests.py','scripts/run_test_plan.py','scripts/test_plan_worker.py','scripts/verify_test_plan.py','scripts/impact_ci.py','scripts/run_bounded_stable_tests.py','.github/workflows/affected_tests.yml','.github/workflows/full_regression.yml')]
    plan['control_blobs']={path:files(ROOT,a.test)[path] for path in controlled}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'mode':plan['mode'],'labels':len(plan['labels']),'reason':a.reason,'bootstrap':bootstrap},ensure_ascii=False))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write(f'mode={plan["mode"]}\n')


if __name__=='__main__':main()

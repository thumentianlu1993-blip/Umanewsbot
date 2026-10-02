#!/usr/bin/env python3
"""真实历史单文件差异回放；只生成选集，不执行业务测试。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.test_impact.core import select_changes
from tools.test_impact.git_input import blob,git


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    catalog=json.loads((ROOT/'tools/test_impact/catalog.json').read_text());rules=json.loads((ROOT/'tools/test_impact/rules.json').read_text())
    cases=[]
    targets=[('server/stable/templates/stable/public/horse_detail.html','horse_page',3),
             ('server/stable/services/japanese_racing_translation.py','news_translation',3),
             ('server/stable/services/historical_batch_runner.py','historical_batch',3),
             ('server/stable/services/race_reference_sources.py','race_parser',1)]
    for path,domain,count in targets:
        commits=git(ROOT,'log','--no-merges',f'-{count}','--format=%H','HEAD','--',path).decode().split()
        for sha in commits:
            base=git(ROOT,'rev-parse',sha+'^').decode().strip()
            try:before=blob(ROOT,base,path).decode()
            except subprocess.CalledProcessError:before=''
            after=blob(ROOT,sha,path).decode()
            plan=select_changes([{'path':path,'before':before,'after':after}],rules,catalog)
            assert domain in plan['domains'] and plan['mode']=='targeted'
            if domain=='horse_page':
                assert 'stable.tests_legacy.P0HorseProfileDataCompletionTests' in plan['labels']
            cases.append({'base_sha':base,'head_sha':sha,'path':path,'scope':'historical-single-file-diff',
                          'mode':plan['mode'],'domains':plan['domains'],'labels':plan['labels']})
    assert len(cases)==10
    a.output.write_text(json.dumps({'cases':cases,'executed_business_tests':0},ensure_ascii=False,indent=2)+'\n')
    print('10 historical single-file diffs: PASS; 0 business tests executed')


if __name__=='__main__':main()

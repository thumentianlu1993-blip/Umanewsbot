#!/usr/bin/env python3
"""核验精确执行集合和完整生命周期，输出有界摘要。"""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.test_impact.core import verify_results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--reports',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();plan=json.loads(a.plan.read_text())
    reports=[json.loads(f.read_text()) for f in sorted(a.reports.rglob('batch-*.json'))]
    result=verify_results(plan,reports)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()

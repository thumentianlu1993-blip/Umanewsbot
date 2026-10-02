#!/usr/bin/env python3
"""共享 synthetic 安全停止/续跑合同，输出 checkpoint 供手动任务保存。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]


def run(output):
    cmd=[sys.executable,str(ROOT/'runtime/research/collect_graded_race_participants.py'),
         '--year','2025','--stage','synthetic_smoke','--output-dir',str(output)]
    for options,expected in [(['--limit','1'],75),(['--resume'],0)]:
        result=subprocess.run(cmd+options,capture_output=True,text=True,timeout=60)
        if result.returncode!=expected:raise ValueError(f'synthetic expected {expected}, got {result.returncode}: {result.stderr[-2000:]}')
    report=json.loads((output/'synthetic_smoke_report.json').read_text())
    if report['byte_equivalent'] is not True or len(report['final_files'])!=7:raise ValueError('synthetic final files mismatch')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output)

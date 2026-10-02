#!/usr/bin/env python3
"""未变化 main 每周检查，失败不因 SHA 相同而被跳过。"""
from datetime import datetime, timezone, timedelta
import json
import os
import re
import subprocess


def should_run(sha, latest, now):
    return (latest is None or latest['conclusion']!='success' or latest['head_sha']!=sha or
            now-datetime.fromisoformat(latest['updated_at'].replace('Z','+00:00'))>=timedelta(days=7))


def main():
    def api(path):return json.loads(subprocess.check_output(['gh','api',path]))
    repo=os.environ['GITHUB_REPOSITORY']
    sha=os.environ.get('REQUESTED_SHA') or api(f'repos/{repo}/commits/main')['sha']
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('exact SHA required')
    if os.environ.get('REQUESTED_SHA'):
        if not os.environ.get('REQUESTED_REASON','').strip():raise ValueError('reason required')
        run=True
    else:
        runs=api(f'repos/{repo}/actions/workflows/full_regression.yml/runs?per_page=100')['workflow_runs']
        latest=None
        for item in runs:
            if item['status']!='completed':continue
            jobs=api(f'repos/{repo}/actions/runs/{item["id"]}/attempts/{item["run_attempt"]}/jobs?per_page=100')['jobs']
            # 跳过只有 decide 的检查；它并非新的成功全量。
            if any(j['name'].endswith('/ tests') and j['conclusion']!='skipped' for j in jobs):
                latest=item;break
        run=should_run(sha,latest,datetime.now(timezone.utc))
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write(f'run={str(run).lower()}\nsha={sha}\n')
    print(json.dumps({'run':run,'sha':sha}))


if __name__=='__main__':main()

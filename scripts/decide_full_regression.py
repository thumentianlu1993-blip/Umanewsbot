#!/usr/bin/env python3
"""未变化 main 每周检查，失败不因 SHA 相同而被跳过。"""
from datetime import datetime, timezone, timedelta
import json
import io
import zipfile
import os
import re
import subprocess


def should_run(sha, latest, now):
    return (latest is None or latest['conclusion']!='success' or latest.get('tested_sha')!=sha or
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
                latest=dict(item)
                if item['conclusion']=='success':
                    artifacts=api(f'repos/{repo}/actions/runs/{item["id"]}/artifacts?per_page=100')['artifacts']
                    evidence=[a for a in artifacts if a['name']==f'impact-{item["id"]}-{item["run_attempt"]}' and not a['expired']]
                    if len(evidence)==1:
                        raw=subprocess.check_output(['gh','api',f'repos/{repo}/actions/artifacts/{evidence[0]["id"]}/zip'])
                        with zipfile.ZipFile(io.BytesIO(raw)) as z:
                            plan=json.loads(z.read('execution-plan.json')); summary=json.loads(z.read('summary.json'))
                        if (summary['status']=='passed' and summary['mode']=='full' and plan['mode']=='full'
                            and plan['run_id']==str(item['id']) and plan['run_attempt']==str(item['run_attempt'])
                            and plan['test_sha']==plan['head_sha']):
                            latest['tested_sha']=plan['test_sha']
                break
        run=should_run(sha,latest,datetime.now(timezone.utc))
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write(f'run={str(run).lower()}\nsha={sha}\n')
    print(json.dumps({'run':run,'sha':sha}))


if __name__=='__main__':main()

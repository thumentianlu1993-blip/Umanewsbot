#!/usr/bin/env python3
"""核对每批证据与固定清单，任何漏项、失败、跳过或不同 SHA 均拒绝。"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'docs/changes/fix-known-test-failures'


def verify(root, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('expected full commit SHA')
    batches = json.loads((PLAN / 'regression_batches.json').read_text())['batches']
    inventory = PLAN / 'failure_inventory.json'
    digest = hashlib.sha256(inventory.read_bytes()).hexdigest()
    seen = set()
    for batch, manifest in batches.items():
        result = json.loads((root / f'bounded-{batch}' / 'result.json').read_text())
        expected = manifest['expected_ids']
        executed = result['executed']
        if (not 0 < len(expected) <= 200 or result['sha'] != sha
                or result['batch'] != batch or result['inventory_sha256'] != digest
                or result['diff_sha256'] != hashlib.sha256(b'').hexdigest()
                or not result['passed'] or result['tests_run'] != len(expected)
                or sorted(result['selected']) != expected or sorted(executed) != expected
                or result['failures'] or result['errors'] or result['skipped']
                or result['unexpected_successes'] or seen.intersection(executed)):
            raise ValueError(f'batch {batch}: identity, completeness or result mismatch')
        seen.update(executed)
    original = json.loads(inventory.read_text())['failures']
    required = {r['replacement'] for r in original}
    if len(original) != 50 or len(required) != 50 or not required.issubset(seen):
        raise ValueError('50 original failures are not fully accounted for')
    return {'sha': sha, 'tests_run': len(seen), 'fixed_failure_ids': len(required), 'passed': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--sha', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.sha), indent=2))

#!/usr/bin/env python3
"""将已逐组确认的名称裁决应用到固定 SHA 的离线目录；不修改原始证据。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from stable.services.hkjc_name_catalog import NameCatalog


def apply_reviews(catalog_bytes, decisions):
    if hashlib.sha256(catalog_bytes).hexdigest() != decisions['catalog_sha256']:
        raise ValueError('review baseline SHA mismatch')
    if decisions.get('schema') != 'hkjc-name-reviews-v1':
        raise ValueError('unsupported review schema')
    catalog = json.loads(catalog_bytes)
    entries = {(r['kind'], r['id']): r for r in catalog['entries']}
    if len(entries) != len(catalog['entries']):
        raise ValueError('duplicate source record IDs')
    touched = {}
    for case in decisions['cases']:
        if case['status'] != 'approved' or not case['decision']:
            raise ValueError('unapproved name review')
        for group in case['groups']:
            rows = [entries[(case['kind'], ident)] for ident in group['ids']]
            names = set().union(*(set(r['names']) for r in rows))
            names.difference_update(group.get('remove_aliases', []))
            names.add(group['target'])
            for row in rows:
                action = {k: deepcopy(group[k]) for k in ('target', 'identity_group', 'identity', 'active_years') if k in group}
                key = (case['kind'], row['id'])
                if key in touched and touched[key] != action:
                    raise ValueError('conflicting reviewed actions')
                touched[key] = action
                row.update(action, names=sorted(names))
                row.setdefault('review_cases', []).append(case['number'])
    NameCatalog(catalog['entries'])
    catalog['review'] = {'baseline_sha256': decisions['catalog_sha256'],
                         'decision_queue_sha256': decisions['decision_queue_sha256'],
                         'case_numbers': [c['number'] for c in decisions['cases']],
                         'changed_evidence_records': len(touched)}
    return catalog


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--decisions', type=Path, required=True)
    parser.add_argument('--race-csv', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.decisions.read_bytes()
    catalog = apply_reviews(args.catalog.read_bytes(), json.loads(raw))
    catalog['review']['actions_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / 'catalog.json'
    path.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / 'catalog.sha256').write_text(sha + '\n')
    from build_hkjc_name_catalog import preview
    summary = preview(catalog, args.race_csv, args.output)
    print(json.dumps({'catalog_sha256': sha, **{k: v for k, v in summary.items() if k != 'examples'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

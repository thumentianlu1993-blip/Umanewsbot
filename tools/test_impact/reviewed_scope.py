"""一次变更的显式选测清单；只在全部字节、模式和基线一致时收敛范围。"""
from .core import digest, safe_path

FIELDS = ('path', 'status', 'before_hash', 'after_hash', 'before_mode', 'after_mode')


def apply_reviewed_scope(selection, *, changes, manifest, base_sha, catalog):
    if (manifest.get('schema_version') != 1 or manifest.get('base_sha') != base_sha
        or not isinstance(manifest.get('reason'), str) or not manifest['reason'].strip()):
        raise ValueError('reviewed scope identity or reason invalid')
    expected = manifest.get('changes', [])
    if not expected or len({r['path'] for r in expected}) != len(expected):
        raise ValueError('reviewed scope changes invalid')
    for row in expected:
        safe_path(row['path'])
    actual = [{k: row[k] for k in FIELDS} for row in changes]
    if sorted(actual, key=lambda r: r['path']) != sorted(expected, key=lambda r: r['path']):
        raise ValueError('reviewed scope changed paths/content/modes drift')
    requested = manifest.get('domains')
    if not isinstance(requested, list) or not requested or any(d not in catalog['domains'] for d in requested):
        raise ValueError('reviewed scope domain invalid')
    domains = set(requested) | {'core'}
    pending = list(domains)
    while pending:
        for dependency in catalog.get('dependencies', {}).get(pending.pop(), []):
            if dependency not in domains:
                domains.add(dependency)
                pending.append(dependency)
    return {**selection, 'mode': 'targeted', 'domains': sorted(domains),
            'labels': sorted({label for domain in domains for label in catalog['domains'][domain]}),
            'reviewed_scope_sha256': digest(manifest),
            'reasons': selection['reasons'] + [{'reason': 'explicit reviewed change scope',
                'justification': manifest['reason'], 'scope_sha256': digest(manifest)}]}

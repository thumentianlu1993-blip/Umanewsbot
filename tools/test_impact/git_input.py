"""只读 Git 输入；任何 Git 错误都阻断计划。"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from .core import safe_path


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def commit(root, value):
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('exact 40-character SHA required')
    if git(root, 'rev-parse', value + '^{commit}').decode().strip() != value:
        raise ValueError('not a commit')
    return value


def files(root, sha):
    entries = {}
    for record in git(root, 'ls-tree', '-rz', sha).split(b'\0'):
        if record:
            meta, path = record.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            path = safe_path(path.decode())
            if mode not in ('100644', '100755') or kind != 'blob':
                raise ValueError(f'non-regular Git entry: {path}')
            entries[path] = oid
    return entries


def blob(root, sha, path):
    return git(root, 'show', sha + ':' + safe_path(path))


def read_json(root, sha, path):
    return json.loads(blob(root, sha, path))


def inputs(root, base, head, test, local=False):
    base, head, test = [commit(root, v) for v in (base, head, test)]
    old, new = files(root, base), files(root, test)
    def modes(sha):
        return {r.split(b'\t',1)[1].decode(): r.split(b' ',1)[0].decode() for r in git(root,'ls-tree','-rz',sha).split(b'\0') if r}
    old_modes, new_modes = modes(base), modes(test)
    index_changes = []
    if not local and test != head:
        parents = git(root, 'show', '-s', '--format=%P', test).decode().split()
        if parents != [base, head]:
            raise ValueError('test SHA is not the exact base/head merge')
    if not local and test == head:
        # 显式单提交 full profile 可用；PR 调用方另要求 merge 提交。
        git(root, 'merge-base', '--is-ancestor', base, head)
    contents = {}
    if local:
        tracked = set(git(root, 'ls-files', '-z').decode().split('\0')) - {''}
        untracked = set(git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')) - {''}
        new = {}
        new_modes = {}
        for record in git(root,'ls-files','--stage','-z').split(b'\0'):
            if not record: continue
            meta, raw_path = record.split(b'\t',1)
            mode, oid, stage = meta.decode().split(); path = safe_path(raw_path.decode())
            if stage != '0': raise ValueError('unmerged local index')
            if mode not in ('100644','100755'): raise ValueError('unsafe index entry')
            if old.get(path)!=oid or old_modes.get(path)!=mode:
                before=blob(root,base,path) if path in old else b''
                after=git(root,'cat-file','blob',oid)
                index_changes.append({'path':path,'before':before.decode('utf-8','replace'),'after':after.decode('utf-8','replace'),'status':'index','before_hash':hashlib.sha256(before).hexdigest(),'after_hash':hashlib.sha256(after).hexdigest(),'mode':mode})
        for path in sorted(tracked | untracked):
            safe_path(path)
            file = Path(root) / path
            if file.is_symlink() or not file.resolve().is_relative_to(Path(root).resolve()):
                raise ValueError(f'unsafe local path: {path}')
            if file.exists():
                contents[path] = file.read_bytes()
                new[path] = git(root, 'hash-object', '--', path).decode().strip()
                new_modes[path] = '100755' if file.stat().st_mode & 0o111 else '100644'
    changes = []
    for path in sorted(old.keys() | new.keys()):
        if old.get(path) == new.get(path) and old_modes.get(path)==new_modes.get(path):
            continue
        before = blob(root, base, path) if path in old else b''
        after = (contents[path] if local else blob(root, test, path)) if path in new else b''
        changes.append({'path': path, 'before': before.decode('utf-8', 'replace'),
                        'after': after.decode('utf-8', 'replace'),
                        'status': 'deleted' if path not in new else 'added' if path not in old else 'modified',
                        'before_hash': hashlib.sha256(before).hexdigest(), 'after_hash': hashlib.sha256(after).hexdigest(), 'before_mode':old_modes.get(path), 'after_mode':new_modes.get(path)})
    from .core import digest
    return {'base_sha': base, 'head_sha': head, 'test_sha': test,
            'test_tree': git(root, 'rev-parse', test + '^{tree}').decode().strip(),
            'source': 'local' if local else 'git', 'content_digest': digest({'files':new,'modes':new_modes,'index':index_changes}),
            'changes': changes + index_changes, 'paths': sorted(new)}

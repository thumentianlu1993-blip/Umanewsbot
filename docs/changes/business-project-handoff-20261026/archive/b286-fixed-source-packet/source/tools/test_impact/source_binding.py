"""Bind an isolated worker to the executor's exact Git archive, using stdlib only."""
import base64
import hashlib
from pathlib import Path
import re
import subprocess


def _sha(value):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{40}', value) is None:
        raise ValueError('exact 40-character SHA required')
    return value


def validate_source_plan(plan):
    if type(plan) is not dict or plan.get('source') != 'git':
        raise ValueError('frozen Git plan required')
    return _sha(plan.get('test_sha')), _sha(plan.get('test_tree'))


def _object(kind, data):
    return hashlib.sha1(kind.encode()+b' '+str(len(data)).encode()+b'\0'+data).hexdigest()


def _tree(entries):
    children = {}
    for path, entry in entries.items():
        first, separator, rest = path.partition('/')
        if separator:
            if first in children and not isinstance(children[first], dict):
                raise ValueError('source path collision')
            children.setdefault(first, {})[rest] = entry
        else:
            if first in children:
                raise ValueError('source path collision')
            children[first] = (entry['mode'], entry['blob'])
    data = b''
    for name, value in sorted(children.items(), key=lambda pair:(pair[0]+('/' if isinstance(pair[1],dict) else '')).encode()):
        mode, oid = ('40000', _tree(value)) if isinstance(value, dict) else value
        data += mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(oid)
    return _object('tree', data)


def verify_source_binding(plan, binding, root, *, require_git_head=False):
    sha, tree = validate_source_plan(plan)
    if type(binding) is not dict or binding.get('test_sha') != sha or binding.get('test_tree') != tree:
        raise ValueError('source binding identity mismatch')
    try:
        raw_commit = base64.b64decode(binding['commit_base64'], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('frozen commit payload required') from exc
    if _object('commit', raw_commit) != sha or raw_commit.split(b'\n', 1)[0] != b'tree '+tree.encode():
        raise ValueError('frozen commit identity mismatch')
    entries = binding.get('files')
    if type(entries) is not dict or not entries:
        raise ValueError('source binding files required')
    root = Path(root).resolve()
    for path, entry in entries.items():
        if type(path) is not str or not path or path.startswith('/') or '\\' in path or any(p in ('', '.', '..') for p in path.split('/')):
            raise ValueError('unsafe source path')
        if type(entry) is not dict or entry.get('mode') not in ('100644', '100755'):
            raise ValueError('non-regular source entry')
        oid = _sha(entry.get('blob'))
        file = root/path
        if file.is_symlink() or not file.resolve().is_relative_to(root) or not file.is_file():
            raise ValueError('missing/unsafe frozen source: '+path)
        mode = '100755' if file.stat().st_mode & 0o111 else '100644'
        if mode != entry['mode'] or _object('blob', file.read_bytes()) != oid:
            raise ValueError('frozen source mismatch: '+path)
    # The entrypoint restores Git metadata for commands that inspect actual HEAD.
    # It is generated control state, outside the committed source tree.
    actual = {str(p.relative_to(root)) for p in root.rglob('*')
              if '.git' != p.relative_to(root).parts[0] and (p.is_file() or p.is_symlink())}
    if actual != set(entries):
        raise ValueError('unexpected frozen source files')
    if _tree(entries) != tree:
        raise ValueError('frozen source tree mismatch')
    if require_git_head:
        if (root/'.git').is_symlink() or not (root/'.git').is_dir():
            raise ValueError('isolated Git metadata required')
        head = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],stderr=subprocess.PIPE).decode().strip()
        if head != sha:
            raise ValueError('actual frozen HEAD mismatch')
    return sha

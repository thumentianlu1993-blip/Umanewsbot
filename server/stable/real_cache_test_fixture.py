"""已保存公开页面的离线测试夹具；验证打包摘要后仅重定位描述中的路径。"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'ci_real_cache'


def verify_real_cache_fixtures(root=FIXTURES):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    expected = {'manifest.json'}
    for entry in manifest['files']:
        path = root / entry['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('unsafe real cache fixture path')
        body = path.read_bytes()
        if len(body) != entry['size'] or hashlib.sha256(body).hexdigest() != entry['sha256']:
            raise ValueError('real cache fixture identity mismatch')
        expected.add(entry['path'])
    if {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()} != expected:
        raise ValueError('unexpected real cache fixture files')
    return root


def fixture_descriptor(path):
    text = Path(path).read_text(encoding='utf-8')
    text = text.replace('@FIXTURE_ROOT@', str(FIXTURES)).replace('@REPOSITORY_ROOT@', str(ROOT))
    return json.loads(text)

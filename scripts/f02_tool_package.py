"""Build and verify immutable F02 Python tool packages. No network operations."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

from scripts import f02_transfer as transfer

class PackageError(ValueError):
    pass

MODULE_FILES = ('scripts/f02_readonly_export.py', 'scripts/f02_transfer.py', 'scripts/f02_docker_adapter.py',
                'scripts/f02_container_probe.py', 'scripts/f02_tool_package.py', 'scripts/f02_receipt_bridge.py')
FILES = {'entry.py', 'scripts/__init__.py', *MODULE_FILES}

# Self-contained standard-library bootstrap verifies all files before importing packaged modules.
ENTRY = '''import hashlib,json,os,pathlib,stat,sys
try:
    assert sys.version_info >= (3,12)
    root=pathlib.Path(__file__).absolute().parent
    assert not any(p.is_symlink() for p in (root,*root.parents))
    names=NAMES
    def read(path,limit):
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            s=os.fstat(f.fileno())
            assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 and s.st_size<=limit
            data=f.read(limit+1)
            assert len(data)<=limit
            return data
    data=read(root/'package.manifest.json',65536)
    assert hashlib.sha256(data).hexdigest()==sys.argv[1]
    m=json.loads(data)
    assert m['schema_version']==1 and m['minimum_python']=='3.12' and set(m['files'])==set(names)
    assert {str(p.relative_to(root)) for p in root.rglob('*')}==set(names)|{'scripts','package.manifest.json'}
    for p in (root,root/'scripts'):
        s=p.lstat();assert stat.S_ISDIR(s.st_mode) and stat.S_IMODE(s.st_mode)==0o700 and s.st_uid==os.geteuid()
    for name in names:
        assert hashlib.sha256(read(root/name,1048576)).hexdigest()==m['files'][name]
    action=sys.argv[2]
    assert action in ('verify','transfer','probe')
    if action=='verify':
        print(json.dumps({'git_sha':m['git_sha'],'manifest_sha256':sys.argv[1]}));sys.exit(0)
    sys.path.insert(0,str(root))
    if action=='transfer':
        from scripts.f02_transfer import main
    else:
        from scripts.f02_container_probe import main
    sys.exit(main(sys.argv[3:]))
except Exception:
    print('{"code":"invalid_tool_package"}');sys.exit(2)
'''.replace('NAMES', repr(sorted(FILES)))


def build_package(payloads, output, git_sha):
    try:
        if set(payloads) != set(MODULE_FILES) or not re.fullmatch('[0-9a-f]{40}', git_sha):
            raise PackageError('invalid_package_inputs')
        if any(not isinstance(data, bytes) or len(data)>1024*1024 for data in payloads.values()):
            raise PackageError('module_budget')
        root = transfer.check_path(output)
        if root.exists():
            raise PackageError('package_exists')
        transfer.mkdir_private(root.parent)
        root.mkdir(mode=0o700)
        (root/'scripts').mkdir(mode=0o700)
        files = dict(payloads, **{'scripts/__init__.py': b'', 'entry.py': ENTRY.encode()})
        for name, data in files.items():
            fd = os.open(root/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
        manifest = {'schema_version': 1, 'git_sha': git_sha, 'minimum_python': '3.12',
                    'files': {name: hashlib.sha256(data).hexdigest() for name,data in files.items()}}
        transfer.atomic_json(root/'package.manifest.json', manifest)
        transfer.fsync_directory(root/'scripts');transfer.fsync_directory(root);transfer.fsync_directory(root.parent)
        digest = hashlib.sha256((root/'package.manifest.json').read_bytes()).hexdigest()
        return verify_package(root, digest)
    except PackageError:
        raise
    except Exception:
        raise PackageError('package_build_failed') from None


def verify_package(root, expected_manifest_sha):
    try:
        if sys.version_info < (3,12):
            raise PackageError('python_version_unsupported')
        root = transfer.private_directory(root)
        data = transfer.read_file(root/'package.manifest.json', 65536)
        if hashlib.sha256(data).hexdigest()!=expected_manifest_sha:
            raise PackageError('package_manifest_mismatch')
        manifest = transfer.parse(data)
        if (set(manifest)!={'schema_version','git_sha','minimum_python','files'} or manifest['schema_version']!=1
                or manifest['minimum_python']!='3.12' or not re.fullmatch('[0-9a-f]{40}',manifest['git_sha'])
                or set(manifest['files'])!=FILES):
            raise PackageError('invalid_package_manifest')
        if {str(p.relative_to(root)) for p in root.rglob('*')} != FILES|{'scripts','package.manifest.json'}:
            raise PackageError('extra_or_missing_package_file')
        transfer.private_directory(root/'scripts')
        for name,digest in manifest['files'].items():
            if not isinstance(digest,str) or hashlib.sha256(transfer.read_file(root/name,1024*1024)).hexdigest()!=digest:
                raise PackageError('module_hash_mismatch')
        return {'git_sha':manifest['git_sha'],'manifest_sha256':expected_manifest_sha,'minimum_python':'3.12'}
    except PackageError:
        raise
    except Exception:
        raise PackageError('invalid_tool_package') from None


def build_from_git(repository, commit_sha, output):
    if not re.fullmatch('[0-9a-f]{40}',commit_sha):
        raise PackageError('invalid_git_sha')
    payloads={}
    try:
        for name in MODULE_FILES:
            result=subprocess.run(['git','-C',str(repository),'show',commit_sha+':'+name],
                                  stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                  shell=False,timeout=5,check=True)
            if len(result.stdout)>1024*1024:
                raise PackageError('module_budget')
            payloads[name]=result.stdout
        return build_package(payloads,output,commit_sha)
    except PackageError:
        raise
    except Exception:
        raise PackageError('fixed_git_object_unavailable') from None

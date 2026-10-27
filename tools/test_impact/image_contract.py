"""固定历史镜像的真实准备与有界证据；worker 不持有 Docker daemon。"""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import time
import uuid
from tempfile import TemporaryDirectory, TemporaryFile
from tools.test_impact.fixture_inputs import _json

NATIVE_ID = 'stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file'
AUDIT_RELATIVE = 'changes/repair-production-migration-history/production_audit.json'
DATABASE_IDENTITY = 'a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c'


def selected(plan):
    return any(NATIVE_ID == label or NATIVE_ID.startswith(label + '.') for label in plan['labels'])


def needs_preparation(plan, *, collect_only, prepare_images, batch):
    return selected(plan) and not batch and (not collect_only or prepare_images)


def read_proof(path):
    path = Path(path)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('image proof must be a regular file')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('image proof must be regular')
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError('oversize image proof')
        return data
    except OSError as exc:
        raise ValueError('image proof unavailable') from exc


def collection_input(selection, collected, proof_root):
    """CI和候选外验证器统一重建实际collection请求，先核原始proof字节。"""
    result = {**selection, 'image_id': collected['image_id']}
    if selected(selection):
        validate_proof(read_proof(Path(proof_root)/'migration-image-proof.json'), collected)
        result['migration_image_proof'] = collected['migration_image_proof']
    elif 'migration_image_proof' in collected:
        raise ValueError('unselected image proof')
    return result


def preparation_command(command, *, observer=None, timeout=60, cwd=None):
    """文件承接输出，避免OwnedObserver.wait与PIPE互锁；同享总截止和清理预留。"""
    with TemporaryFile() as out, TemporaryFile() as err:
        kwargs = dict(stdout=out, stderr=err, timeout=timeout, cwd=cwd)
        if observer is None:
            result = subprocess.run(command, **kwargs)
        else:
            result = observer.run(command, 'migration-image-preparation', **kwargs)
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(16*1024*1024+1), err.read(16*1024*1024+1)
        if max(len(stdout), len(stderr)) > 16*1024*1024:
            raise ValueError('oversize image preparation output')
        return subprocess.CompletedProcess(command, result.returncode, stdout.decode(), stderr.decode())


def validate_proof(raw, plan):
    """字节摘要由只读 control 绑定；不从 worker 环境接受证据或路径。"""
    descriptor = plan.get('migration_image_proof')
    if (type(raw) is not bytes or len(raw) > 65536 or type(descriptor) is not dict
            or set(descriptor) != {'version', 'sha256'} or type(descriptor['version']) is not int
            or descriptor['version'] != 1 or hashlib.sha256(raw).hexdigest() != descriptor['sha256']):
        raise ValueError('missing or unbound image proof')
    proof = _json(raw)
    if (type(proof) is not dict or set(proof) != {'version','test_sha','test_tree','source','image_id','inspect','runtime','cleanup'}
            or type(proof['version']) is not int or proof['version'] != 1
            or proof['source'] != _MIGRATION_IMAGE_SOURCE):
        raise ValueError('image proof schema or source mismatch')
    for key in ('test_sha', 'test_tree'):
        if (type(proof[key]) is not str or re.fullmatch('[0-9a-f]{40}', proof[key]) is None
                or proof[key] == '0'*40 or proof[key] != plan.get(key)):
            raise ValueError('image proof test source mismatch')
    _migration_image_values(proof['image_id'], proof['inspect'], proof['runtime'], proof['source']['sha'])
    owner = proof['inspect']['Config']['Labels'].get('org.umanews.test-preparation')
    if type(owner) is not str or re.fullmatch('[0-9a-f]{32}', owner) is None:
        raise ValueError('missing unique image preparation owner')
    runtime = proof['runtime']
    if (set(runtime) != {'release_commit','marker_hex','audit_files','audit_sha256','database_identity_sha256'}
            or runtime['audit_files'] != [AUDIT_RELATIVE]
            or runtime['audit_sha256'] != _MIGRATION_IMAGE_SOURCE['pins']['docs/'+AUDIT_RELATIVE]
            or runtime['database_identity_sha256'] != DATABASE_IDENTITY):
        raise ValueError('actual image audit content mismatch')
    cleanup = proof['cleanup']
    if (type(cleanup) is not dict or set(cleanup) != {'created_image','removed'}
            or type(cleanup['created_image']) is not bool or type(cleanup['removed']) is not bool
            or cleanup['created_image'] != cleanup['removed']):
        raise ValueError('image cleanup incomplete')
    return proof

# Reviewed image source is independent of this test-fix commit.
_MIGRATION_IMAGE_SOURCE = {
    "sha": "1dd5e0a508957672bcddd1c33e454fbbef1b75c1",
    "tree": "67e755d385725fa7404cba822bf65d74f50403cf",
    "pins": {
        "Dockerfile": "57bfb54b98425911b0a58d08c7634f654253a1374d8b5e3c2f221bf637b3177d",
        ".dockerignore": "ce8e0d28818b57e42592d09d2de35ced17af0a0d5cb86aabd993523f80605790",
        "requirements.txt": "f3fd408c04cae78ed13d5175fe8cc04674fcde4efab9d9f18d569652eddf3f59",
        "docs/changes/repair-production-migration-history/production_audit.json": "2d3fba0d7d97ff9d706b22ef8a8ae1f7719aa1db4772176b95cc8954e2f6105c",
        "server/stable/services/historical_calendar_release_b_schema.py": "05eeaa404dc8bca309ed18a7ffd19bb2febcf1b2a43fd26034ba11f0bcb6aae0",
    },
}


def _migration_image_source(repository, source_sha, reviewed):
    if (not isinstance(source_sha, str) or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None
            or source_sha == "0" * 40 or source_sha != reviewed["sha"]):
        raise ValueError("explicit nonzero reviewed source SHA required")
    def git(*args):
        try:
            return subprocess.check_output(["git", "-C", str(repository), *args], stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            raise ValueError("reviewed Git object unavailable") from exc
    if git("cat-file", "-t", source_sha).strip() != b"commit":
        raise ValueError("reviewed source must be a commit")
    tree = git("rev-parse", source_sha + "^{tree}").decode().strip()
    if tree != reviewed["tree"]:
        raise ValueError("reviewed source tree mismatch")
    files = {}
    for record in git("ls-tree", "-rz", "--full-tree", source_sha).split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        name = path.decode()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError("nonregular source member")
        files[name] = {"mode": mode, "blob": oid}
    for path, expected in reviewed["pins"].items():
        if path not in files or hashlib.sha256(git("cat-file", "blob", files[path]["blob"])).hexdigest() != expected:
            raise ValueError("reviewed input byte pin mismatch")
    return {"sha": source_sha, "tree": tree, "files": files, "pins": dict(reviewed["pins"])}


def _assert_migration_image_context(context, source):
    context = Path(context)
    if context.is_symlink() or not context.is_dir() or stat.S_IMODE(context.stat().st_mode) != 0o700:
        raise ValueError("private source context required")
    expected = source["files"]
    directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}
    seen = set()
    for path in context.rglob("*"):
        name = path.relative_to(context).as_posix()
        current = path.lstat()
        if stat.S_ISDIR(current.st_mode):
            if name not in directories:
                raise ValueError("unexpected context directory")
            continue
        if not stat.S_ISREG(current.st_mode) or name not in expected:
            raise ValueError("unexpected or unsafe context member")
        identity = expected[name]
        if stat.S_IMODE(current.st_mode) != (0o755 if identity["mode"] == "100755" else 0o644):
            raise ValueError("context file mode drift")
        body = path.read_bytes()
        oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        if oid != identity["blob"] or (name in source["pins"] and hashlib.sha256(body).hexdigest() != source["pins"][name]):
            raise ValueError("context byte identity drift")
        seen.add(name)
    if seen != set(expected):
        raise ValueError("context member missing")


def _migration_image_archive_context(archive, source, context):
    context = Path(context)
    if context.exists() or context.is_symlink():
        raise ValueError("fresh context required")
    expected = source["files"]
    directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}
    contents, seen = {}, set()
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as tar:
            for member in tar:
                name = member.name.rstrip("/") if member.isdir() else member.name
                path = Path(name)
                if (not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name or name in seen):
                    raise ValueError("unsafe or duplicate archive member")
                seen.add(name)
                if member.isdir():
                    if name not in directories:
                        raise ValueError("unexpected archive directory")
                    continue
                if not member.isfile() or name not in expected or member.mode & 0o7000:
                    raise ValueError("nonregular or unexpected archive member")
                identity = expected[name]
                if bool(member.mode & 0o111) != (identity["mode"] == "100755"):
                    raise ValueError("archive executable mode drift")
                handle = tar.extractfile(member)
                if handle is None:
                    raise ValueError("missing archive bytes")
                body = handle.read()
                oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
                if oid != identity["blob"]:
                    raise ValueError("archive blob identity drift")
                contents[name] = body
    except (tarfile.TarError, EOFError) as exc:
        raise ValueError("invalid Git archive") from exc
    if set(contents) != set(expected):
        raise ValueError("archive member missing")
    # No archive paths are materialized until the entire exact member set passes.
    context.mkdir(mode=0o700)
    for name, body in contents.items():
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(body)
        path.chmod(0o755 if expected[name]["mode"] == "100755" else 0o644)
    _assert_migration_image_context(context, source)


def _migration_image_id(raw):
    if not isinstance(raw, str) or re.fullmatch(r"sha256:[0-9a-f]{64}\n?", raw) is None:
        raise ValueError("one immutable image ID required")
    return raw.removesuffix("\n")


def _migration_image_values(image_id, inspected, runtime, expected_sha):
    if (not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None
            or expected_sha == "0" * 40):
        raise ValueError("explicit expected source revision required")
    if _migration_image_id(image_id) != image_id or not isinstance(inspected, dict) or inspected.get("Id") != image_id:
        raise ValueError("inspect object must be the same immutable image ID")
    config = inspected.get("Config")
    if not isinstance(config, dict) or not isinstance(config.get("Labels"), dict) or not isinstance(config.get("Env"), list):
        raise ValueError("missing image revision metadata")
    environment = config["Env"]
    if any(not isinstance(value, str) or "=" not in value for value in environment):
        raise ValueError("malformed image environment")
    releases = [value for value in environment if value.split("=", 1)[0] == "UMANEWS_RELEASE_COMMIT"]
    if (config["Labels"].get("org.opencontainers.image.revision") != expected_sha
            or releases != ["UMANEWS_RELEASE_COMMIT=" + expected_sha]
            or not isinstance(runtime, dict)
            or runtime.get("release_commit") != expected_sha
            or runtime.get("marker_hex") != (expected_sha + "\n").encode().hex()):
        raise ValueError("each image revision value must equal expected SHA")


def _equal(actual, expected, message='image contract mismatch'):
    if actual != expected:
        raise ValueError(message)


def prepare_image_proof(repository, plan, output, observer=None):
    if observer is not None:
        observer.admission(600)
    def run(command, *, timeout=60, cwd=None):
        return preparation_command(command, observer=observer, timeout=timeout, cwd=cwd)
    source = _migration_image_source(repository, _MIGRATION_IMAGE_SOURCE["sha"], _MIGRATION_IMAGE_SOURCE)
    image_id = None
    created_image = False
    with TemporaryDirectory(prefix="migration-image-contract-") as directory:
        private = Path(directory)
        context = private / "source"
        archive = subprocess.check_output(["git", "-C", str(repository), "archive", source["sha"]])
        _migration_image_archive_context(archive, source, context)
        iidfile = private / "image-id"
        _assert_migration_image_context(context, source)
        before = run(
            ["docker", "image", "ls", "--no-trunc", "--quiet"],
            timeout=60,
        )
        _equal(before.returncode, 0, before.stderr)
        existing_ids = {_migration_image_id(value) for value in before.stdout.splitlines()}
        owner = uuid.uuid4().hex
        container_name = 'migration-image-contract-'+owner
        reader_started = False
        cidfile = Path(output)/'owned-cids'/(container_name+'.cid')
        primary = None
        try:
            build = run(
                ["docker", "build", "--iidfile", str(iidfile), "--label",
                 "org.umanews.test-preparation="+owner, "--build-arg",
                 "UMANEWS_RELEASE_COMMIT=" + source["sha"], "."],
                cwd=context, timeout=600,
            )
            (Path(output)/'migration-image-build.log').write_text(build.stdout+build.stderr)
            _equal(build.returncode, 0, "historical image build failed; see migration-image-build.log")
            image_id = _migration_image_id(iidfile.read_text())
            created_image = image_id not in existing_ids
            _assert_migration_image_context(context, source)
            inspect = run(
                ["docker", "image", "inspect", image_id],
                timeout=60,
            )
            _equal(inspect.returncode, 0, inspect.stderr)
            inspected = json.loads(inspect.stdout)
            _equal(type(inspected), list)
            _equal(len(inspected), 1)
            _equal(inspected[0]["Config"]["Labels"].get("org.umanews.test-preparation"), owner)
            code = (
                "from pathlib import Path; import django; django.setup(); "
                "from stable.services.historical_calendar_release_b_schema import "
                "AUDIT_PATH, load_reviewed_production_audit; "
                "expected=Path('/app/docs/changes/repair-production-migration-history/production_audit.json'); "
                "assert AUDIT_PATH == expected; "
                "files=sorted(str(p.relative_to('/app/docs')) for p in Path('/app/docs').rglob('*') if p.is_file()); "
                "assert files == ['changes/repair-production-migration-history/production_audit.json'], files; "
                "assert load_reviewed_production_audit()['database_identity_sha256'] == "
                "'a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c'; "
                "import os,json,hashlib; "
                "assert hashlib.sha256(expected.read_bytes()).hexdigest() == "
                + repr(source["pins"]["docs/changes/repair-production-migration-history/production_audit.json"])
                + "; print(json.dumps({'release_commit':os.environ.get('UMANEWS_RELEASE_COMMIT'),"
                "'marker_hex':Path('/app/.umanews-release-commit').read_bytes().hex(),"
                "'audit_files':files,'audit_sha256':hashlib.sha256(expected.read_bytes()).hexdigest(),"
                "'database_identity_sha256':load_reviewed_production_audit()['database_identity_sha256']}))"
            )
            reader = ["docker", "run", "--name", container_name, "--network", "none", "--cap-drop", "ALL",
                      "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp:rw,size=128m",
                      "--pids-limit", "128", "--memory", "1g", "--cpus", "1", "-e",
                      "DJANGO_SETTINGS_MODULE=app.settings", "--entrypoint", "python", image_id, "-c", code]
            if observer is not None:
                cidfile.parent.mkdir(exist_ok=True)
                reader[2:2] = ['--cidfile', str(cidfile)]
                observer.start(container_name, cidfile, 'migration-image', 'migration-image-preparation', image_id=image_id)
            reader_started = True
            read = run(reader, timeout=60)
            _equal(read.returncode, 0, read.stderr)
            _migration_image_values(image_id, inspected[0], json.loads(read.stdout), source["sha"])
            _assert_migration_image_context(context, source)
        except BaseException as exc:
            primary = exc
            raise
        finally:
            cleanup_errors = []
            cleanup_end = min(time.monotonic()+40, observer.deadline) if observer is not None else time.monotonic()+40
            try:
                if reader_started:
                    if observer is not None:
                        observer.cleanup(container_name, cidfile)
                    else:
                        cleanup_container = subprocess.run(['docker','rm','-f',container_name], capture_output=True, text=True, timeout=20)
                        absent = subprocess.run(['docker','container','inspect',container_name], capture_output=True, text=True, timeout=5)
                        if (cleanup_container.returncode != 0 or absent.returncode != 1 or absent.stdout.strip()
                                or absent.stderr.strip() not in ('Error: No such container: '+container_name, 'Error: No such object: '+container_name)):
                            raise ValueError('image reader container cleanup unconfirmed')
            except BaseException as exc:
                cleanup_errors.append(exc)
            try:
                if image_id is not None and created_image:
                    remaining = cleanup_end-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('image cleanup budget exhausted: '+image_id)
                    cleanup = subprocess.run(['docker', 'image', 'rm', image_id],
                                             text=True, capture_output=True, timeout=min(remaining,30))
                    _equal(cleanup.returncode, 0, cleanup.stderr)
            except BaseException as exc:
                cleanup_errors.append(exc)
            if cleanup_errors:
                if primary is not None:
                    for error in cleanup_errors:
                        primary.add_note('image preparation cleanup: '+repr(error))
                else:
                    raise cleanup_errors[0]
    proof = dict(version=1, test_sha=plan['test_sha'], test_tree=plan['test_tree'],
                 source=_MIGRATION_IMAGE_SOURCE, image_id=image_id, inspect=inspected[0],
                 runtime=json.loads(read.stdout),
                 cleanup=dict(created_image=created_image, removed=created_image))
    raw = (json.dumps(proof, sort_keys=True)+'\n').encode()
    descriptor = dict(version=1, sha256=hashlib.sha256(raw).hexdigest())
    validate_proof(raw, {**plan, 'migration_image_proof': descriptor})
    return raw, descriptor

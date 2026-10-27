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
import uuid
from tempfile import TemporaryDirectory
from tools.test_impact.fixture_inputs import _json

NATIVE_ID = 'stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file'
AUDIT_RELATIVE = 'changes/repair-production-migration-history/production_audit.json'
DATABASE_IDENTITY = 'a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c'


def selected(plan):
    return any(NATIVE_ID == label or NATIVE_ID.startswith(label + '.') for label in plan['labels'])


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


def prepare_image_proof(repository, plan, output):
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
        before = subprocess.run(
            ["docker", "image", "ls", "--no-trunc", "--quiet"],
            text=True, capture_output=True, timeout=60, check=False,
        )
        _equal(before.returncode, 0, before.stderr)
        existing_ids = {_migration_image_id(value) for value in before.stdout.splitlines()}
        container_name = 'migration-image-contract-'+uuid.uuid4().hex
        try:
            build = subprocess.run(
                ["docker", "build", "--iidfile", str(iidfile), "--build-arg",
                 "UMANEWS_RELEASE_COMMIT=" + source["sha"], "."],
                cwd=context, text=True, capture_output=True, timeout=600, check=False,
            )
            (Path(output)/'migration-image-build.log').write_text(build.stdout+build.stderr)
            _equal(build.returncode, 0, "historical image build failed; see migration-image-build.log")
            image_id = _migration_image_id(iidfile.read_text())
            created_image = image_id not in existing_ids
            _assert_migration_image_context(context, source)
            inspect = subprocess.run(
                ["docker", "image", "inspect", image_id],
                text=True, capture_output=True, timeout=60, check=False,
            )
            _equal(inspect.returncode, 0, inspect.stderr)
            inspected = json.loads(inspect.stdout)
            _equal(type(inspected), list)
            _equal(len(inspected), 1)
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
            read = subprocess.run(
                ["docker", "run", "--name", container_name, "--rm", "--network", "none", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp:rw,size=128m", "--pids-limit", "128", "--memory", "1g", "--cpus", "1", "-e",
                 "DJANGO_SETTINGS_MODULE=app.settings", "--entrypoint", "python", image_id, "-c", code],
                text=True, capture_output=True, timeout=60, check=False,
            )
            _equal(read.returncode, 0, read.stderr)
            _migration_image_values(image_id, inspected[0], json.loads(read.stdout), source["sha"])
            _assert_migration_image_context(context, source)
        finally:
            cleanup_container = subprocess.run(['docker','rm','-f',container_name], capture_output=True, text=True, timeout=30)
            absent = subprocess.run(['docker','container','inspect',container_name], capture_output=True, text=True, timeout=30)
            if absent.returncode != 1 or 'No such container' not in absent.stderr:
                raise ValueError('image reader container cleanup unconfirmed')
            if image_id is not None and created_image:
                cleanup = subprocess.run(
                    ["docker", "image", "rm", image_id],
                    text=True, capture_output=True, timeout=60, check=False,
                )
                _equal(cleanup.returncode, 0, cleanup.stderr)
    proof = dict(version=1, test_sha=plan['test_sha'], test_tree=plan['test_tree'],
                 source=_MIGRATION_IMAGE_SOURCE, image_id=image_id, inspect=inspected[0],
                 runtime=json.loads(read.stdout),
                 cleanup=dict(created_image=created_image, removed=created_image))
    raw = (json.dumps(proof, sort_keys=True)+'\n').encode()
    descriptor = dict(version=1, sha256=hashlib.sha256(raw).hexdigest())
    validate_proof(raw, {**plan, 'migration_image_proof': descriptor})
    return raw, descriptor

"""从独立摘要绑定的单份 HKJC 缓存准备未审阅读产物；不连接或写数据库。"""
import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

MAX_BYTES = 128 * 1024
MAX_DEPTH = 32
PACKET_FIELDS = {
    "schema_version", "source_file", "cache_ref", "source_ref", "snapshot",
    "entity_versions", "as_of", "max_age_seconds", "profile_baseline",
}
BASIC_FIELDS = ("country", "sex", "color", "birth_date", "owner_name", "trainer_name", "breeder_name")
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _reject(reason):
    raise CommandError(reason) from None


def _parts(value, reason, *, absolute=False):
    if type(value) is not str or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        _reject(reason)
    if value.startswith("/") != absolute:
        _reject(reason)
    parts = value[1:].split("/") if absolute else value.split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        _reject(reason)
    return parts


@contextmanager
def _root(value, reason, *, private=False):
    parts = _parts(value, reason, absolute=True)
    fd = os.open("/", DIRECTORY_FLAGS)
    try:
        for part in parts:
            next_fd = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
            _reject(reason)
        yield fd
    except OSError:
        _reject(reason)
    finally:
        os.close(fd)


@contextmanager
def _parent(root_fd, relative, reason, *, private=False):
    parts = _parts(relative, reason)
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            info = os.fstat(fd)
            if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
                _reject(reason)
        yield fd, parts[-1]
    except OSError:
        _reject(reason)
    finally:
        os.close(fd)


def _read(root_fd, relative, size_reason):
    with _parent(root_fd, relative, "input_path") as (parent_fd, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        except OSError:
            _reject("input_path")
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                _reject("input_path")
            if info.st_size > MAX_BYTES:
                _reject(size_reason)
            chunks, total = [], 0
            while total <= MAX_BYTES:
                chunk = os.read(fd, min(65536, MAX_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > MAX_BYTES:
                _reject(size_reason)
            # Hash/parse the same bytes read through this FD, never reopen by filename.
            return b"".join(chunks)
        except OSError:
            _reject("input_path")
        finally:
            os.close(fd)


def _bound(raw, expected, missing, mismatch):
    if type(expected) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected):
        _reject(missing)
    if hashlib.sha256(raw).hexdigest() != expected:
        _reject(mismatch)


def _strict_packet(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError
            obj[key] = value
        return obj

    def nonfinite(value):
        raise ValueError

    def bounded(value, depth=0):
        if depth > MAX_DEPTH:
            raise ValueError
        if type(value) is dict:
            for item in value.values():
                bounded(item, depth + 1)
        elif type(value) is list:
            for item in value:
                bounded(item, depth + 1)
        elif value is not None and type(value) not in (str, int, bool):
            raise ValueError

    try:
        packet = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
        bounded(packet)
    except (ValueError, UnicodeError, RecursionError):
        _reject("input_json")
    if type(packet) is not dict or set(packet) != PACKET_FIELDS:
        _reject("input_schema")
    if (packet["schema_version"] != "h03-prepare-input.v1"
            or any(type(packet[k]) is not str or not packet[k]
                   for k in ("source_file", "cache_ref", "source_ref", "as_of", "profile_baseline"))
            or type(packet["snapshot"]) is not dict or type(packet["entity_versions"]) is not dict
            or type(packet["max_age_seconds"]) is not int or packet["max_age_seconds"] < 0):
        _reject("input_schema")
    try:
        baseline = datetime.fromisoformat(packet["profile_baseline"].replace("Z", "+00:00"))
        if baseline.tzinfo is None or baseline.utcoffset() != timezone.utc.utcoffset(baseline):
            raise ValueError
    except ValueError:
        _reject("input_schema")
    return packet


def _prepare(packet, raw, source_sha):
    # Lazy module references retain the existing public adapter/planner and real consumer.
    from stable.services import horse_cache_reuse, horse_source_cache_reuse_adapter
    from stable.services import p0_horse_completion_adapters as canonical

    try:
        record = horse_source_cache_reuse_adapter.adapt_hkjc_source_cache(
            raw, expected_sha256=source_sha, ref=packet["cache_ref"], source_ref=packet["source_ref"])
    except horse_source_cache_reuse_adapter.CacheReuseAdapterError as exc:
        _reject(exc.code)
    try:
        plan = horse_cache_reuse.plan_cache_reuse(
            packet["snapshot"], [record], packet["entity_versions"],
            as_of=packet["as_of"], max_age_seconds=packet["max_age_seconds"])
    except (ValueError, TypeError, OverflowError):
        _reject("cache_not_reusable")
    if len(plan["decisions"]) != 1 or len(plan["candidates"]) != 1:
        _reject("cache_not_reusable")
    candidate, decision = plan["candidates"][0], plan["decisions"][0]
    if (candidate["action"] != "reusable" or decision["status"] != "reusable"
            or not re.fullmatch(r"profile:[1-9][0-9]*", candidate["entity_key"])
            or set(packet["entity_versions"]) != {candidate["entity_key"]}
            or not decision["profile_exists"] or decision["public_state"] != "unpublished"
            or candidate["cache_refs"] != [packet["cache_ref"]]):
        _reject("cache_not_reusable")
    # The adapter already performed strict original-JSON validation without a source client.
    source = json.loads(record["content"])
    request = canonical.P0HorseCompletionRequest(
        candidate_key=candidate["idempotency_key"], region="hong_kong",
        horse_name=source.get("identity", {}).get("horse_name", ""),
        source_url=source["source"]["url"], external_horse_id=source["source"]["external_horse_id"],
        candidate_source_name="hkjc")
    try:
        payload = canonical.REGION_ADAPTERS["hong_kong"].normalize(source, request)
    except (ValueError, TypeError):
        _reject("cache_validation")
    if payload["failure_reason"]:
        _reject("cache_validation")
    payload["reviewed"] = False
    return payload, plan, candidate


def _descriptor_path(fd):
    info = os.fstat(fd)
    for parent in ("/proc/self/fd", "/dev/fd"):
        path = Path(parent) / str(fd)
        try:
            visible = path.stat()
        except OSError:
            continue
        if (visible.st_dev, visible.st_ino) == (info.st_dev, info.st_ino):
            return path
    _reject("output_path")


def _same_entry(fd, name, expected):
    try:
        current = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except OSError:
        return False
    return (current.st_dev, current.st_ino) == (expected.st_dev, expected.st_ino)


def _write_private(fd, name, data, owned):
    temporary = "." + uuid.uuid4().hex + ".tmp"
    stream_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    owned.add(temporary)
    with os.fdopen(stream_fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    # Targets are new files in this exclusively created, private directory.
    os.rename(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
    owned.remove(temporary)
    owned.add(name)


def _publish(root_fd, relative, payload, manifest):
    from stable.services import p0_horse_completion_adapters as canonical
    from stable.services import p0_horse_completion_review as review

    with _parent(root_fd, relative, "output_path", private=True) as (parent_fd, name):
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            _reject("output_exists")
        except OSError:
            _reject("output_path")
        created_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        try:
            directory_fd = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
        except OSError:
            if _same_entry(parent_fd, name, created_info):
                try:
                    os.rmdir(name, dir_fd=parent_fd)
                except OSError:
                    pass
            _reject("output_path")
        info = os.fstat(directory_fd)
        owned, success = set(), False
        try:
            if not _same_entry(parent_fd, name, created_info) or (info.st_dev, info.st_ino) != (created_info.st_dev, created_info.st_ino):
                _reject("output_path")
            bridge = _descriptor_path(directory_fd)
            _write_private(directory_fd, "combined_candidates.jsonl", canonical._jsonl_bytes([payload]), owned)
            row = canonical._review_row(payload)
            display_row = {k: review._excel_safe(v) for k, v in row.items()}
            _write_private(directory_fd, "review.csv", canonical._csv_bytes([display_row], list(row)), owned)
            _write_private(directory_fd, "manifest.json", canonical._canonical_json_bytes(manifest), owned)
            # Existing workbook writes .tmp then replace; precreate it privately, no process-wide umask change.
            temp_fd = os.open("review.xlsx.tmp", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=directory_fd)
            os.close(temp_fd)
            owned.add("review.xlsx.tmp")
            owned.add("review.xlsx")  # Include a consumer failure after its final rename.
            review.build_batch_review_workbook(
                manifest=manifest, artifact_dir=bridge, output_path=bridge / "review.xlsx")
            owned.discard("review.xlsx.tmp")
            with _parent(directory_fd, "review.xlsx", "output_path") as (fd, filename):
                file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                        _reject("output_path")
                    os.fchmod(file_fd, 0o600)
                finally:
                    os.close(file_fd)
            if not _same_entry(parent_fd, name, info):
                _reject("output_path")
            os.fsync(directory_fd)
            success = True
        except CommandError:
            raise
        except (OSError, ValueError, TypeError, review.P0HorseBatchError):
            _reject("artifact_build_failed")
        finally:
            if not success:
                # Operate only through our held private FD; never recursively delete a caller path.
                for filename in owned:
                    try:
                        os.unlink(filename, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
                if _same_entry(parent_fd, name, info):
                    try:
                        os.rmdir(name, dir_fd=parent_fd)
                    except OSError:
                        pass  # Never remove unexpected files created by somebody else.
            os.close(directory_fd)


class Command(BaseCommand):
    help = "从独立 SHA 绑定的本地 HKJC 缓存生成未审预览与阅读工作簿；不提供 apply/commit。"
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        for name in ("input-root", "input", "expected-input-sha256",
                     "expected-source-sha256", "output-root", "output-dir"):
            parser.add_argument("--" + name, required=True)

    def handle(self, *args, **options):
        with ExitStack() as stack:
            input_fd = stack.enter_context(_root(options["input_root"], "input_path"))
            raw_packet = _read(input_fd, options["input"], "input_size")
            _bound(raw_packet, options["expected_input_sha256"], "input_hash_unbound", "input_hash_mismatch")
            packet = _strict_packet(raw_packet)
            raw = _read(input_fd, packet["source_file"], "cache_size")
            _bound(raw, options["expected_source_sha256"], "content_hash_unbound", "content_hash_mismatch")
            payload, plan, candidate = _prepare(packet, raw, options["expected_source_sha256"])
            output_fd = stack.enter_context(_root(options["output_root"], "output_path", private=True))
            input_path, output_path = Path(options["input_root"]), Path(options["output_root"])
            if input_path == output_path or input_path in output_path.parents or output_path in input_path.parents:
                _reject("output_path")
            manifest = {
                "artifact_type": "h03_local_pending_preview", "schema_version": 1,
                "status": "local_pending_review", "reviewed": False, "read_only": True,
                "input_sha256": options["expected_input_sha256"],
                "source_sha256": options["expected_source_sha256"],
                "h02_sha256": plan["content_sha256"],
                "candidate_idempotency_key": candidate["idempotency_key"],
                "entity_key": candidate["entity_key"], "entity_version": candidate["entity_version"],
                "profile_baseline": packet["profile_baseline"],
                "horses": [{"candidate_key": payload["candidate_key"],
                            "profile_id": int(candidate["entity_key"].split(":", 1)[1]),
                            "queue_reasons": ["local_pending_review"]}],
            }
            _publish(output_fd, options["output_dir"], payload, manifest)
            # JSON escapes terminal controls independently of untouched canonical payload values.
            self.stdout.write(json.dumps({
                "status": "prepared", "reason": "local_pending_review", "reviewed": False,
                "basic_profile": {k: payload["basic_profile"][k] for k in BASIC_FIELDS},
                "artifact_dir": str(output_path / options["output_dir"]),
            }, ensure_ascii=True, allow_nan=False))

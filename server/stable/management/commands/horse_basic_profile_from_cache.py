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

from stable.services.horse_basic_profile_prepare_input import (
    MAX_BYTES, MAX_DEPTH, PACKET_FIELDS, BASIC_FIELDS, DIRECTORY_FLAGS,
    _reject, _parts, _root, _parent, _read, _bound, _strict_packet, _prepare,
)


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

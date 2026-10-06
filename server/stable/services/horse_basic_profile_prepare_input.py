"""H03 窄纯文件/输入重建合同；默认 prepare bytes/参数/严格JSON语义不变。"""
import hashlib
import json
import math
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timezone

from django.core.management.base import CommandError

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


def _read(root_fd, relative, size_reason, *, private=False, metadata=False):
    with _parent(root_fd, relative, "input_path", private=private) as (parent_fd, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        except OSError:
            _reject("input_path")
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                _reject("input_path")
            if private and info.st_uid != os.getuid():
                _reject("input_owner")
            if private and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                _reject("input_private")
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
            raw = b"".join(chunks)
            if private:
                final = os.fstat(fd)
                if any(getattr(info, key) != getattr(final, key) for key in ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size", "st_mtime_ns")):
                    _reject("input_changed")
            return (raw, info) if metadata else raw
        except OSError:
            _reject("input_path")
        finally:
            os.close(fd)


def _bound(raw, expected, missing, mismatch):
    if type(expected) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected):
        _reject(missing)
    if hashlib.sha256(raw).hexdigest() != expected:
        _reject(mismatch)


def _strict_json(raw, *, allow_float=False):
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
        elif type(value) is float and allow_float:
            if not math.isfinite(value):
                raise ValueError
        elif value is not None and type(value) not in (str, int, bool):
            raise ValueError

    try:
        packet = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
        bounded(packet)
    except (ValueError, UnicodeError, RecursionError):
        _reject("input_json")
    return packet


def _strict_packet(raw):
    packet = _strict_json(raw)
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




def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _equal(left, right, reason):
    if _canonical(left) != _canonical(right):
        _reject(reason)


def _utc(value, reason):
    if type(value) is not str:
        _reject(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError
        return parsed
    except ValueError:
        _reject(reason)


def _review(raw):
    value = _strict_json(raw)
    fields = {"schema_version", "code_sha", "inputs", "target", "scope", "module_reviews", "reviewer_id", "before", "after"}
    if type(value) is not dict or set(value) != fields or value["schema_version"] != "h03-basic-profile-reviewed-input.v1":
        _reject("review_schema")
    if type(value["code_sha"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", value["code_sha"]):
        _reject("review_code")
    if type(value["reviewer_id"]) is not int or value["reviewer_id"] < 1:
        _reject("review_actor")
    inputs = value["inputs"]
    if type(inputs) is not dict or set(inputs) != {"packet", "cache", "manifest", "candidates"}:
        _reject("review_inputs")
    for entry in inputs.values():
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            _reject("review_inputs")
        _parts(entry["path"], "input_path")
        if type(entry["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            _reject("review_inputs")
    target = value["target"]
    if type(target) is not dict or set(target) != {"profile_id", "entity_key", "entity_version", "profile_baseline", "h02_sha256", "candidate_idempotency_key"}:
        _reject("review_target")
    if type(target["profile_id"]) is not int or not 0 < target["profile_id"] <= 10**12:
        _reject("review_target")
    _equal(value["scope"], {"module": "profile", "fields": list(BASIC_FIELDS)}, "review_scope")
    reviews = value["module_reviews"]
    if type(reviews) is not dict or set(reviews) != {"profile"}:
        _reject("review_metadata")
    review = reviews["profile"]
    if type(review) is not dict or set(review) != {"status", "reviewed_by", "approved_at", "decision_source_reference"}:
        _reject("review_metadata")
    if review["status"] not in ("approved", "ignore") or any(type(review[k]) is not str or not review[k].strip() for k in review):
        _reject("review_metadata")
    _utc(review["approved_at"], "review_time")
    for role in ("before", "after"):
        fields = value[role]
        if type(fields) is not dict or set(fields) != set(BASIC_FIELDS):
            _reject("review_fields")
        if any((v is not None and type(v) is not str) if k == "birth_date" else type(v) is not str for k, v in fields.items()):
            _reject("review_fields")
    return value


class _CapturedInputs:
    """One bounded read per role; aliases use only metadata from the held input FD."""
    def __init__(self):
        self.identities = set()
        self.total = 0

    def read(self, fd, path, expected):
        raw, metadata = _read(fd, path, "input_size", private=True, metadata=True)
        identity = metadata.st_dev, metadata.st_ino
        if identity in self.identities:
            _reject("input_alias")
        self.identities.add(identity)
        self.total += len(raw)
        if self.total > 5 * MAX_BYTES:
            _reject("input_total_size")
        _bound(raw, expected, "input_hash_unbound", "input_hash_mismatch")
        return raw


def _bundle(fd, inputs, capture, *, packet_raw=None):
    if packet_raw is None:
        packet_raw = capture.read(fd, inputs["packet"]["path"], inputs["packet"]["sha256"])
    packet = _strict_packet(packet_raw)
    if packet["source_file"] != inputs["cache"]["path"]:
        _reject("source_path_mismatch")
    cache = capture.read(fd, inputs["cache"]["path"], inputs["cache"]["sha256"])
    manifest = _strict_json(capture.read(fd, inputs["manifest"]["path"], inputs["manifest"]["sha256"]))
    display = _strict_json(capture.read(fd, inputs["candidates"]["path"], inputs["candidates"]["sha256"]), allow_float=True)
    payload, plan, candidate = _prepare(packet, cache, inputs["cache"]["sha256"])
    profile_id = int(candidate["entity_key"].split(":", 1)[1])
    expected_manifest = {
        "artifact_type": "h03_local_pending_preview", "schema_version": 1,
        "status": "local_pending_review", "reviewed": False, "read_only": True,
        "input_sha256": inputs["packet"]["sha256"], "source_sha256": inputs["cache"]["sha256"],
        "h02_sha256": plan["content_sha256"], "candidate_idempotency_key": candidate["idempotency_key"],
        "entity_key": candidate["entity_key"], "entity_version": candidate["entity_version"],
        "profile_baseline": packet["profile_baseline"],
        "horses": [{"candidate_key": payload["candidate_key"], "profile_id": profile_id, "queue_reasons": ["local_pending_review"]}],
    }
    _equal(manifest, expected_manifest, "manifest_mismatch")
    _equal(display, payload, "candidates_mismatch")
    target = {"profile_id": profile_id, "entity_key": candidate["entity_key"],
              "entity_version": candidate["entity_version"], "profile_baseline": packet["profile_baseline"],
              "h02_sha256": plan["content_sha256"], "candidate_idempotency_key": candidate["idempotency_key"]}
    source = json.loads(cache)
    return {"packet": packet, "cache": cache, "candidate": candidate, "target": target,
            "after": payload["basic_profile"], "source_time": source["source"]["fetched_at"]}

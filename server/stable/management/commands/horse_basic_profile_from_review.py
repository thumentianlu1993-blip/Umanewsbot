"""独立文件审核的窄 H03 入口；原件/当前 staff/私有目标/时效绑定，不公开。"""
import argparse
import json
import re
import hashlib
import os
import stat
from contextlib import ExitStack
from datetime import date, timezone as utc_timezone
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services import horse_basic_profile_from_cache as h03
from stable.services.horse_basic_profile_prepare_input import (
    BASIC_FIELDS, MAX_BYTES, DIRECTORY_FLAGS, _reject, _root, _parent, _utc,
    _equal, _review, _bundle, _CapturedInputs,
)


from django.core.management.base import BaseCommand, CommandError


def _positive(value):
    if not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise argparse.ArgumentTypeError("actor-id must be a positive integer")
    return int(value)


class Command(BaseCommand):
    help = "记录独立审核文件，真实回滚模拟或消费七字段；不提供公开/取源。"
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group(required=True)
        for name in ("record-review", "dry-run", "commit"):
            modes.add_argument("--" + name, action="store_true")
        parser.add_argument("--input-root", required=True)
        parser.add_argument("--actor-id", type=_positive, required=True)
        parser.add_argument("--code-sha", required=True)
        for name in ("packet", "manifest", "candidates", "expected-input-sha256",
                     "expected-source-sha256", "expected-manifest-sha256",
                     "expected-candidates-sha256", "decision-source-reference",
                     "output-root", "output-dir", "review-root", "review-input",
                     "expected-reviewed-input-sha256"):
            parser.add_argument("--" + name)
        parser.add_argument("--decision", choices=("approved", "ignore"))

    def handle(self, *args, **options):
        modes = [name for name in ("record_review", "dry_run", "commit") if options.get(name)]
        if len(modes) != 1:
            raise CommandError("exactly_one_mode_required")
        if not re.fullmatch(r"[0-9a-f]{40}", str(options.get("code_sha") or "")):
            raise CommandError("code_sha_invalid")
        if type(options.get("actor_id")) is not int or options["actor_id"] < 1:
            raise CommandError("actor_id_invalid")
        mode = modes[0]
        record = ("packet", "manifest", "candidates", "expected_input_sha256",
                  "expected_source_sha256", "expected_manifest_sha256",
                  "expected_candidates_sha256", "decision", "decision_source_reference",
                  "output_root", "output_dir")
        consume = ("review_root", "review_input", "expected_reviewed_input_sha256")
        required, forbidden = (record, consume) if mode == "record_review" else (consume, record)
        if any(not isinstance(options.get(name), str) or not options[name].strip()
               for name in ("input_root", *required)):
            raise CommandError("mode_arguments_required")
        if any(options.get(name) is not None for name in forbidden):
            raise CommandError("mode_arguments_conflict")
        if mode == "record_review" and options["decision"] not in ("approved", "ignore"):
            raise CommandError("decision_invalid")
        for name in required:
            if name.endswith("sha256") and not re.fullmatch(r"[0-9a-f]{64}", options[name]):
                raise CommandError("expected_sha256_invalid")
        result = _execute(mode, options)
        # Serialize inside atomic before commit; this final write is deliberately after commit.
        # BrokenPipe propagates, retaining the already durable candidate/log/binding.
        self.stdout.write(result)


def _now():
    return timezone.now().astimezone(utc_timezone.utc)


def _freshness(bundle, decision=None):
    now = _now()
    source = _utc(bundle["source_time"], "source_time")
    as_of = _utc(bundle["packet"]["as_of"], "packet_time")
    if source > now or as_of > now:
        _reject("source_or_packet_future")
    if (now - source).total_seconds() > bundle["packet"]["max_age_seconds"]:
        _reject("source_expired")
    if decision and _utc(decision["module_reviews"]["profile"]["approved_at"], "review_time") > now:
        _reject("review_future")
    return now


def _staff(actor):
    if actor is None or not actor.is_active or not actor.is_staff:
        _reject("actor_not_staff")


def _private(profile):
    if profile is None:
        _reject("target_missing")
    if profile.review_status not in (models.HorseProfileStatus.DRAFT, models.HorseProfileStatus.READY) or profile.hidden_at is not None:
        _reject("target_not_private")


def _fields(profile):
    return {key: value.isoformat() if isinstance(value, date) else value
            for key in BASIC_FIELDS for value in [getattr(profile, key)]}


def _request(bundle, actor):
    packet = bundle["packet"]
    return dict(snapshot=packet["snapshot"], candidate=bundle["candidate"], raw_bytes=bundle["cache"],
                expected_sha256=bundle["inputs"]["cache"]["sha256"], ref=packet["cache_ref"],
                source_ref=packet["source_ref"], entity_versions=packet["entity_versions"], as_of=packet["as_of"],
                max_age_seconds=packet["max_age_seconds"], expected_updated_at=_utc(packet["profile_baseline"], "profile_baseline"), actor=actor)


def _binding(decision, digest):
    return {"reviewed_input_sha256": digest, "code_sha": decision["code_sha"], "reviewer_id": decision["reviewer_id"],
            "module_reviews": decision["module_reviews"], "inputs": decision["inputs"], "scope": decision["scope"]}


def _save_binding(candidate, binding):
    candidate.raw_payload = dict(candidate.raw_payload, review_input_binding=binding)
    candidate.save(update_fields=["raw_payload"])


def _same_inode(parent_fd, name, info):
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)


def _write_review(root_fd, relative, raw):
    """New directory/file only. Cleanup unlinks only the inode this call owns."""
    with _parent(root_fd, relative, "output_path", private=True) as (parent_fd, name):
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            _reject("output_exists")
        except OSError:
            _reject("review_output_failed")
        created = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        directory_fd = None
        file_info = None
        success = False
        try:
            directory_fd = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
            directory_info = os.fstat(directory_fd)
            if not _same_inode(parent_fd, name, directory_info) or (created.st_dev, created.st_ino) != (directory_info.st_dev, directory_info.st_ino):
                _reject("output_path")
            if directory_info.st_uid != os.getuid() or stat.S_IMODE(directory_info.st_mode) != 0o700:
                _reject("output_path")
            fd = os.open("reviewed-input.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            file_info = os.fstat(fd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if not _same_inode(directory_fd, "reviewed-input.json", file_info) or not _same_inode(parent_fd, name, directory_info):
                _reject("output_path")
            os.fsync(directory_fd)
            success = True
        except OSError:
            _reject("review_output_failed")
        finally:
            if not success:
                if directory_fd is not None and file_info is not None and _same_inode(directory_fd, "reviewed-input.json", file_info):
                    os.unlink("reviewed-input.json", dir_fd=directory_fd)
                if _same_inode(parent_fd, name, created):
                    try:
                        os.rmdir(name, dir_fd=parent_fd)
                    except OSError:
                        pass  # Unexpected entries or replaced paths belong to someone else.
            if directory_fd is not None:
                os.close(directory_fd)


def _serialize(result):
    return json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False)


def _record(options, bundle, output_fd):
    actor = get_user_model().objects.filter(pk=options["actor_id"]).first()
    _staff(actor)
    profile = models.HorseProfile.objects.filter(pk=bundle["target"]["profile_id"]).first()
    _private(profile)
    if profile.updated_at != _utc(bundle["packet"]["profile_baseline"], "profile_baseline"):
        _reject("stale_baseline")
    now = _freshness(bundle)
    decision = {"schema_version": "h03-basic-profile-reviewed-input.v1", "code_sha": options["code_sha"],
                "inputs": bundle["inputs"], "target": bundle["target"],
                "scope": {"module": "profile", "fields": list(BASIC_FIELDS)},
                "module_reviews": {"profile": {"status": options["decision"], "reviewed_by": actor.get_username(),
                    "approved_at": now.isoformat(), "decision_source_reference": options["decision_source_reference"]}},
                "reviewer_id": actor.pk, "before": _fields(profile), "after": bundle["after"]}
    raw = (_serialize(decision) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES:
        _reject("review_size")
    digest = hashlib.sha256(raw).hexdigest()
    _write_review(output_fd, options["output_dir"], raw)
    return _serialize({"mode": "record-review", "status": "recorded", "committed": False, "published": False,
                       "decision": options["decision"], "review_input_sha256": digest,
                       "review_input": str(Path(options["output_root"]) / options["output_dir"] / "reviewed-input.json"),
                       "before": decision["before"], "after": decision["after"]})


def _consume(mode, options, bundle, decision, digest):
    _equal(decision["code_sha"], options["code_sha"], "review_code_mismatch")
    _equal(decision["reviewer_id"], options["actor_id"], "review_actor_mismatch")
    _equal(decision["target"], bundle["target"], "review_target_mismatch")
    _equal(decision["after"], bundle["after"], "review_after_mismatch")
    _freshness(bundle, decision)
    with transaction.atomic():
        # no_key allows existing H03 FK key-share, while serializing a real later revocation.
        actor = get_user_model().objects.select_for_update(no_key=True).filter(pk=options["actor_id"]).first()
        _staff(actor)
        if actor.get_username() != decision["module_reviews"]["profile"]["reviewed_by"]:
            _reject("review_actor_mismatch")
        profile = models.HorseProfile.objects.select_for_update().filter(pk=bundle["target"]["profile_id"]).first()
        _private(profile)
        _freshness(bundle, decision)  # Lock waits cannot extend source/approval validity.
        if decision["module_reviews"]["profile"]["status"] == "ignore":
            if profile.updated_at != _utc(bundle["packet"]["profile_baseline"], "profile_baseline"):
                _reject("stale_baseline")
            _equal(_fields(profile), decision["before"], "review_before_mismatch")
            _freshness(bundle, decision)
            return _serialize({"mode": mode.replace("_", "-"), "status": "ignored", "committed": False,
                               "published": False, "review_input_sha256": digest, "entity_key": bundle["target"]["entity_key"]})
        consumed = list(models.HorseProfileDataCandidate.objects.select_for_update().filter(
            profile=profile, module=models.HorseProfileModule.PROFILE, source_name=h03.SOURCE_ROLE,
            raw_payload__h02_idempotency_key=bundle["candidate"]["idempotency_key"])[:2])
        expected_binding = _binding(decision, digest)
        if len(consumed) > 1:
            _reject("consumption_ambiguous")
        if consumed:
            existing = consumed[0]
            if "review_input_binding" not in existing.raw_payload:
                _reject("review_binding_missing")
            _equal(existing.raw_payload["review_input_binding"], expected_binding, "review_binding_conflict")
        else:
            if profile.updated_at != _utc(bundle["packet"]["profile_baseline"], "profile_baseline"):
                _reject("stale_baseline")
            _equal(_fields(profile), decision["before"], "review_before_mismatch")
        result = h03.apply_basic_profile_from_cache(**_request(bundle, actor))
        if result.get("status") not in ("applied", "already_applied"):
            _reject(result.get("reason", "h03_blocked"))
        stored = models.HorseProfileDataCandidate.objects.select_for_update().get(pk=result["candidate_id"])
        if result["status"] == "applied":
            if consumed:
                _reject("consumption_receipt_invalid")
            _save_binding(stored, expected_binding)
        else:
            _equal(stored.raw_payload.get("review_input_binding"), expected_binding, "review_binding_conflict")
        profile.refresh_from_db()
        stored.refresh_from_db()
        if result["status"] == "applied":
            _equal(_fields(profile), result["after"], "h03_readback_mismatch")
        _equal(stored.raw_payload.get("review_input_binding"), expected_binding, "review_binding_conflict")
        # Recheck current authority/validity within the same outer transaction before commit/rollback.
        actor.refresh_from_db()
        _staff(actor)
        if actor.get_username() != decision["module_reviews"]["profile"]["reviewed_by"]:
            _reject("review_actor_mismatch")
        _private(profile)
        _freshness(bundle, decision)
        output = {"mode": mode.replace("_", "-"), "status": result["status"], "committed": mode == "commit",
                  "review_input_sha256": digest, "entity_key": bundle["target"]["entity_key"],
                  "h02_key": bundle["candidate"]["idempotency_key"], "before": result["before"], "after": result["after"],
                  "updated_fields": result["updated_fields"], "skipped_locked": result["skipped_locked"],
                  "candidate_id": result["candidate_id"], "published": False}
        if mode == "dry_run":
            output.update(status="dry_run", dry_run=True, simulated_status=result["status"], candidate_id=None,
                          simulated_counts={"candidates": models.HorseProfileDataCandidate.objects.filter(profile=profile).count(),
                          "operation_logs": models.OperationLog.objects.filter(target_type="horse_profile", target_id=str(profile.pk), action_type="horse_candidate_applied").count()})
        serialized = _serialize(output)  # Serialization failures rollback, unlike postcommit stdout failures.
        if mode == "dry_run":
            transaction.set_rollback(True)
    return serialized


def _execute(mode, options):
    from stable.services.horse_basic_profile_prepare_input import _strict_packet
    capture = _CapturedInputs()
    with ExitStack() as stack:
        input_fd = stack.enter_context(_root(options["input_root"], "input_path", private=True))
        if mode == "record_review":
            raw = capture.read(input_fd, options["packet"], options["expected_input_sha256"])
            packet = _strict_packet(raw)
            inputs = {"packet": {"path": options["packet"], "sha256": options["expected_input_sha256"]},
                      "cache": {"path": packet["source_file"], "sha256": options["expected_source_sha256"]},
                      "manifest": {"path": options["manifest"], "sha256": options["expected_manifest_sha256"]},
                      "candidates": {"path": options["candidates"], "sha256": options["expected_candidates_sha256"]}}
            bundle = _bundle(input_fd, inputs, capture, packet_raw=raw)
            bundle["inputs"] = inputs
            output_fd = stack.enter_context(_root(options["output_root"], "output_path", private=True))
            input_path, output_path = Path(options["input_root"]), Path(options["output_root"])
            ii, oi = os.fstat(input_fd), os.fstat(output_fd)
            if (ii.st_dev, ii.st_ino) == (oi.st_dev, oi.st_ino) or input_path == output_path or input_path in output_path.parents or output_path in input_path.parents:
                _reject("output_path")
            return _record(options, bundle, output_fd)
        review_fd = stack.enter_context(_root(options["review_root"], "input_path", private=True))
        raw_review = capture.read(review_fd, options["review_input"], options["expected_reviewed_input_sha256"])
        decision = _review(raw_review)
        bundle = _bundle(input_fd, decision["inputs"], capture)
        bundle["inputs"] = decision["inputs"]
        return _consume(mode, options, bundle, decision, options["expected_reviewed_input_sha256"])

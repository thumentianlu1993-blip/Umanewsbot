"""B053私有offline组合消费者：真实read→封闭模型预算→checkpoint→Article。

B055仅修复已接纳E03真实RED的完成态收据重投；新候选实际GREEN仍待验证。
"""
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
import os
from threading import get_ident
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone
from stable.models import ManagedReadonlyTaskBudget, TranslationRun
from . import managed_readonly_steps as ro, translation_recovery as recovery, translation_retry_budget as core

PREFIX = "m02_readonly_"
PLAN_KEY = PREFIX + "plan_v1"
PROGRESS_KEY = PREFIX + "progress_v1"
FINAL_KEY = PREFIX + "final_v1"
PROVENANCE_KEY = "readonly_provenance_v1"
CONTROL_KEYS = {PLAN_KEY, PROGRESS_KEY, FINAL_KEY}
STATES = {"registered", "read_ready", "model_started", "checkpoint_saved", "final_applied",
          "blocked_unknown", "blocked_fence"}
EXIT_REASONS = {"plan_invalid", "identity_invalid", "version_changed", "source_changed", "grant_revoked",
                "deadline_expired", "tool_exhausted", "read_unknown", "model_start_unknown", "usage_unknown",
                "usage_unreconciled", "model_refused", "model_unavailable", "checkpoint_invalid", "storage_failed"}
UNKNOWN_REASONS = {"read_unknown", "model_start_unknown", "usage_unknown"}
IDENTITY_FIELDS = {"operation_uuid", "parent_budget_uuid", "read_budget_uuid", "article_id", "run_id",
                   "claimed_at", "claim_execution_uuid", "source_site", "source_article_id", "input_sha256",
                   "policy_sha256", "provider", "model", "workflow_version", "query_version", "result_version",
                   "permission_epoch", "opened_at", "deadline_at"}
FIXED_STEPS = [{"step_key": "source_excerpt:1", "tool": "source_excerpt_v1", "params": {"body_chars": 256}},
               {"step_key": "translation_result:1", "tool": "translate_full_source_v1", "params": {}}]
FIXED_LIMITS = {"tool_limit": 1, "request_limit": 2, "quality_round_limit": 2, "overall_seconds": 600}


class RegisteredJobRefusal(ValueError):
    pass


def _fail(reason="registered_plan_invalid"):
    raise RegisteredJobRefusal(reason)


def _json_bytes(value):
    """全集/精确builtin/有界深度节点；不运行自定义对象钩子。"""
    seen, nodes = set(), 0
    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 1024 or depth > 8:
            _fail()
        kind = type(item)
        if kind in (dict, list):
            if id(item) in seen:
                _fail()
            seen.add(id(item))
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str or len(key.encode()) > 2048:
                        _fail()
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            seen.remove(id(item))
        elif kind is str:
            if len(item.encode()) > 2048:
                _fail()
        elif kind is int:
            if not -(2**63) <= item < 2**63:
                _fail()
        elif item is not None:
            _fail()
    visit(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _fields(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _fail()


def _int(value, minimum=0, maximum=2**63-1):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail()


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail()


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            _fail()
    except (ValueError, TypeError, AttributeError) as exc:
        raise RegisteredJobRefusal("registered_plan_invalid") from exc


def _stamp(value):
    try:
        if type(value) is not str:
            _fail()
        stamp = datetime.fromisoformat(value)
        if stamp.utcoffset() is None or stamp.astimezone(dt_timezone.utc).isoformat() != value:
            _fail()
        return stamp
    except (ValueError, TypeError) as exc:
        raise RegisteredJobRefusal("registered_plan_invalid") from exc


def _iso(value):
    return value.astimezone(dt_timezone.utc).isoformat()


def _version(value):
    if type(value) is not int or value != 1:
        _fail("registered_plan_unknown_version")


def _signed(value, payload_fields):
    _fields(value, {"schema_version", "payload", "payload_sha256"})
    _version(value["schema_version"])
    _fields(value["payload"], payload_fields)
    _digest(value["payload_sha256"])
    if _sha(value["payload"]) != value["payload_sha256"]:
        _fail()
    return value["payload"]


def decode_control(raw):
    """只decode控制键；business metadata/既有大checkpoint沿原codec，不计新16KiB限额。"""
    if type(raw) is not dict or any(type(k) is not str for k in raw):
        _fail()
    controls = {k: v for k, v in raw.items() if k.startswith(PREFIX)}
    if set(controls) - CONTROL_KEYS:
        _fail("registered_plan_unknown_version")
    if PLAN_KEY not in controls or PROGRESS_KEY not in controls:
        _fail()
    if len(_json_bytes(controls)) > 16384:
        _fail()
    for key, value in controls.items():
        if len(_json_bytes(value)) > (8192 if key == PLAN_KEY else 4096):
            _fail()
    plan = raw[PLAN_KEY]
    payload = _signed(plan, {"plan_uuid", "job_kind", "plan_origin", "identity", "steps", "limits"})
    _uuid(payload["plan_uuid"])
    if (payload["job_kind"] != "readonly_translation_retry_v1"
            or payload["plan_origin"] != "program_fixed_translation_retry_v1"
            or _json_bytes(payload["steps"]) != _json_bytes(FIXED_STEPS)
            or _json_bytes(payload["limits"]) != _json_bytes(FIXED_LIMITS)):
        _fail()
    identity = payload["identity"]
    _fields(identity, IDENTITY_FIELDS)
    for key in ("operation_uuid", "parent_budget_uuid", "read_budget_uuid", "claim_execution_uuid"):
        _uuid(identity[key])
    for key in ("input_sha256", "policy_sha256"):
        _digest(identity[key])
    for key in ("article_id", "run_id"):
        _int(identity[key], 1)
    _int(identity["permission_epoch"])
    for key, limit in (("source_site", 32), ("source_article_id", 255), ("provider", 128), ("model", 255),
                       ("workflow_version", 64), ("query_version", 64), ("result_version", 64)):
        if type(identity[key]) is not str or not 0 < len(identity[key]) <= limit:
            _fail()
    opened, claimed, deadline = (_stamp(identity[key]) for key in ("opened_at", "claimed_at", "deadline_at"))
    if not opened <= claimed < deadline <= opened + timedelta(seconds=600):
        _fail()
    progress = raw[PROGRESS_KEY]
    _fields(progress, {"schema_version", "plan_sha256", "revision", "state", "model_owner_token",
                       "owner_binding_sha256", "last_provider_attempt_index", "read_reference", "exit_reason"})
    _version(progress["schema_version"])
    if progress["plan_sha256"] != plan["payload_sha256"] or type(progress["state"]) is not str or progress["state"] not in STATES:
        _fail()
    _int(progress["revision"])
    _int(progress["last_provider_attempt_index"], 0, 2)
    owner, binding, read, reason = (progress[k] for k in ("model_owner_token", "owner_binding_sha256", "read_reference", "exit_reason"))
    if (owner is None) != (binding is None):
        _fail()
    if owner is not None:
        _uuid(owner); _digest(binding)
    if read is not None:
        _fields(read, {"step_uuid", "result_sha256"}); _uuid(read["step_uuid"]); _digest(read["result_sha256"])
    state, attempt = progress["state"], progress["last_provider_attempt_index"]
    if state == "registered" and (read is not None or owner is not None or attempt != 0):
        _fail()
    if state == "read_ready" and (read is None or owner is not None or attempt != 0):
        _fail()
    if state in {"model_started", "checkpoint_saved", "final_applied"} and (read is None or owner is None or attempt == 0):
        _fail()
    if (owner is None and attempt != 0) or (owner is not None and (attempt == 0 or read is None)):
        _fail()
    if state.startswith("blocked_"):
        if type(reason) is not str or reason not in EXIT_REASONS or ((state == "blocked_unknown") != (reason in UNKNOWN_REASONS)):
            _fail()
    elif reason is not None:
        _fail()
    if (FINAL_KEY in raw) != (state == "final_applied"):
        _fail()
    if FINAL_KEY in raw:
        final = _signed(raw[FINAL_KEY], {"plan_sha256", "claim_execution_uuid", "article_id", "run_id", "checkpoint_sha256",
                                        "read_step_uuid", "read_result_sha256", "applied_at"})
        for key in ("plan_sha256", "checkpoint_sha256", "read_result_sha256"):
            _digest(final[key])
        _uuid(final["claim_execution_uuid"]); _uuid(final["read_step_uuid"])
        _int(final["article_id"], 1); _int(final["run_id"], 1)
        applied = _stamp(final["applied_at"])
        if not claimed <= applied < deadline or any(final[k] != identity[k] for k in ("article_id", "run_id", "claim_execution_uuid")):
            _fail()
        if (final["plan_sha256"] != plan["payload_sha256"] or final["read_step_uuid"] != read["step_uuid"]
                or final["read_result_sha256"] != read["result_sha256"]):
            _fail()
    # return detached strict builtin snapshot, not mutable aliases from raw/provider.
    return json.loads(_json_bytes(controls))


def decode_control_json(encoded):
    if type(encoded) is not str or len(encoded.encode()) > 16384:
        _fail()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail()
            result[key] = value
        return result
    try:
        return decode_control(json.loads(encoded, object_pairs_hook=unique))
    except (ValueError, TypeError, RecursionError) as exc:
        raise RegisteredJobRefusal("registered_plan_invalid") from exc


def has_registered_job(raw):
    return type(raw) is dict and any(type(k) is str and k.startswith(PREFIX) for k in raw)


def registered_article_pending(article_id):
    """只读route fence；锁后writer也再核此标记，不能仅靠一次无锁分类。"""
    return any(has_registered_job(raw) for raw in TranslationRun.objects.filter(
        article_id=article_id, status="started").values_list("raw_response", flat=True))


def ordinary_run_refusal(run):
    return "registered_job_wrapper_required" if run is not None and has_registered_job(run.raw_response) else ""


def _business_metadata_without_reserved_keys(metadata):
    """两个持久化边界均拒绝provider伪造claim、result、job或程序provenance。"""
    if metadata is None:
        return {}
    if type(metadata) is not dict or any(type(k) is not str for k in metadata):
        raise recovery.TranslationCheckpointError("reserved metadata invalid")
    if any(k in {recovery.CLAIM_KEY, recovery.RESULT_KEY, PROVENANCE_KEY} or k.startswith(PREFIX) for k in metadata):
        raise recovery.TranslationCheckpointError("reserved metadata overwrite")
    return metadata


def business_metadata(metadata):
    """私有checkpoint保持原精确JSON类型、深度和大小围栏。"""
    return json.loads(recovery._checkpoint_json(_business_metadata_without_reserved_keys(metadata)))


def ordinary_business_metadata(metadata):
    """普通JSONField语义允许tuple转数组，仍拒绝控制键及不可持久化值。"""
    metadata = _business_metadata_without_reserved_keys(metadata)
    try:
        return json.loads(json.dumps(metadata, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise recovery.TranslationCheckpointError("ordinary metadata encoding") from exc


def _dependencies():
    now = timezone.now()
    try:
        parent_binding = recovery._current_offline_budget_binding()
    except recovery.ManagedTranslationBudgetBlocked as exc:
        raise RegisteredJobRefusal("registered_scope_mismatch") from exc
    if parent_binding is None:
        _fail("registered_scope_missing")
    try:
        binding, scope = ro._current_scope(now)
    except ro.ReadonlyRefusal as exc:
        raise RegisteredJobRefusal("registered_scope_mismatch") from exc
    from . import translation
    try:
        sdk = translation._require_offline_sdk_dependency(binding.scope_nonce)
    except recovery.ManagedTranslationBudgetBlocked as exc:
        raise RegisteredJobRefusal("registered_dependency_missing") from exc
    reader = ro._read_dependency.get()
    if (type(reader) is not ro._ClosedSourceExcerptReader or reader.closed
            or reader.owner != (scope.nonce, os.getpid(), get_ident())):
        _fail("registered_dependency_missing")
    return binding, scope, sdk


def _completed_claim_reason(article, run, envelope):
    """仅锁内完成态归属校验；不授予executing权限，不改claim/Article/Run。"""
    if article is None or run is None:
        return "claim_changed"
    controls = decode_control(run.raw_response)
    if controls[PROGRESS_KEY]["state"] != "final_applied":
        return "claim_already_consumed"
    claim = run.raw_response.get(recovery.CLAIM_KEY)
    if (type(claim) is not dict or claim.get("phase") != "completed"
            or claim.get("claimed_at") != envelope.claimed_at or run.status != "success"
            or article.translation_status != "translated" or article.translation_started_at is not None):
        return "claim_changed"
    identity = controls[PLAN_KEY]["payload"]["identity"]
    if (identity["article_id"] != article.pk or identity["run_id"] != run.pk
            or identity["claimed_at"] != _iso(datetime.fromisoformat(envelope.claimed_at))
            or identity["claim_execution_uuid"] != claim.get("claim_execution_uuid")):
        return "identity_invalid"
    try:
        checkpoint, _ = _private_checkpoint(run.raw_response.get(recovery.RESULT_KEY), controls, envelope)
        if not recovery._checkpoint_matches_claim(checkpoint, claim):
            return "checkpoint_invalid"
    except (recovery.TranslationCheckpointError, KeyError):
        return "checkpoint_invalid"
    final = controls[FINAL_KEY]["payload"]
    if (final["checkpoint_sha256"] != checkpoint["payload_sha256"]
            or article.translated_at is None or _iso(article.translated_at) != final["applied_at"]):
        return "checkpoint_invalid"
    return ""


def _locked_registration_context(binding, scope, sdk, envelope, *, phases, allow_completed=False):
    """仅登记/read fixture prepare前置；不发SDK permit，不写request/read计数。"""
    ro._envelope_valid(envelope)
    parent, reason = core._locked_root(binding.identity)
    if parent is None or reason:
        _fail("registered_scope_mismatch")
    ro._parent_identity_valid(parent, binding.identity)
    root = ManagedReadonlyTaskBudget.objects.select_for_update().filter(pk=scope.root_pk).first()
    if (root is None or root.parent_budget_id != parent.pk or root.operation_uuid != parent.operation_uuid
            or sdk._budget_pk != parent.pk or parent.retired_at is not None):
        _fail("registered_scope_mismatch")
    article, run, reason = recovery._locked_translation_claim(
        envelope.article_id, envelope.run_id, envelope.claimed_at, phase=phases, now=timezone.now())
    if reason == "claim_already_consumed" and allow_completed:
        reason = _completed_claim_reason(article, run, envelope)
    if reason:
        _fail(reason)
    claim = run.raw_response[recovery.CLAIM_KEY]
    actual = core._actual_now(timezone.now())
    deadline = min(root.deadline_at, datetime.fromisoformat(claim["deadline_at"]))
    if (root.state != "open" or root.permission_epoch != scope.permission_epoch
            or root.allowed_tools != [ro.QUERY_VERSION]):
        _fail("grant_revoked")
    if actual >= deadline:
        _fail("deadline_expired")
    if ((root.workflow_version, root.query_version, root.result_version) != (ro.WORKFLOW_VERSION, ro.QUERY_VERSION, ro.RESULT_VERSION)
            or (scope.workflow_version, scope.query_version, scope.result_version) != (ro.WORKFLOW_VERSION, ro.QUERY_VERSION, ro.RESULT_VERSION)):
        _fail("version_changed")
    if ((root.article_pk_snapshot, root.source_site_snapshot, root.source_article_id_snapshot, root.source_sha256,
         root.opened_at, root.deadline_at) != (parent.article_pk_snapshot, parent.source_site_snapshot,
         parent.source_article_id_snapshot, parent.source_sha256, parent.opened_at, parent.deadline_at)
            or article.pk != root.article_pk_snapshot
            or (article.source_site, article.source_article_id) != (root.source_site_snapshot, root.source_article_id_snapshot)
            or recovery.translation_input_sha256(article) != root.source_sha256):
        _fail("source_changed")
    # Step locks precede SDK ledger locks even in registration/route guard.
    list(root.steps.select_for_update().order_by("pk"))
    claim_uuid, reason = recovery._claim_uuid_history_reason(parent, article, run, envelope.claimed_at)
    if reason or claim_uuid is None:
        _fail("identity_invalid")
    if (root.tool_read_limit != 1 or parent.request_limit != 2 or parent.deadline_at - parent.opened_at != timedelta(seconds=600)):
        _fail("registered_plan_invalid")
    identity = {"operation_uuid": str(parent.operation_uuid), "parent_budget_uuid": str(parent.budget_uuid),
                "read_budget_uuid": str(root.read_budget_uuid), "article_id": article.pk, "run_id": run.pk,
                "claimed_at": _iso(datetime.fromisoformat(envelope.claimed_at)), "claim_execution_uuid": str(claim_uuid),
                "source_site": str(article.source_site), "source_article_id": article.source_article_id,
                "input_sha256": root.source_sha256, "policy_sha256": parent.policy_sha256,
                "provider": parent.provider_snapshot, "model": parent.model_snapshot, "workflow_version": root.workflow_version,
                "query_version": root.query_version, "result_version": root.result_version,
                "permission_epoch": root.permission_epoch, "opened_at": _iso(parent.opened_at), "deadline_at": _iso(deadline)}
    return parent, root, article, run, identity


def _validate_live_controls(controls, parent, root, run):
    """锁后结构与真实ledger校验；只拒绝，绝不修复进度/授予model permit。"""
    identity = controls[PLAN_KEY]["payload"]["identity"]
    progress = controls[PROGRESS_KEY]
    steps = list(root.steps.all())  # locked already by registration context
    if len(steps) > 1 or root.tool_reads_reserved != len(steps):
        _fail()
    expected = {k: identity[k] for k in ("operation_uuid", "parent_budget_uuid", "read_budget_uuid", "article_id",
        "run_id", "claimed_at", "claim_execution_uuid", "source_site", "source_article_id", "input_sha256",
        "deadline_at", "workflow_version", "query_version", "result_version", "permission_epoch")}
    for step in steps:
        ro._step_identity(step, expected, {"body_chars": 256})
        if step.state == "completed":
            ro._validated_result(step, expected, {"body_chars": 256})
    reference = progress["read_reference"]
    if reference is not None and (not steps or steps[0].state != "completed"
            or reference != {"step_uuid": str(steps[0].step_uuid), "result_sha256": steps[0].result_sha256}):
        _fail()
    attempts = list(parent.request_attempts.filter(claim_execution_uuid=UUID(identity["claim_execution_uuid"])))
    indices = sorted(attempt.provider_attempt_index for attempt in attempts)
    index = progress["last_provider_attempt_index"]
    if indices != list(range(1, index + 1)) or parent.requests_reserved != len(attempts):
        _fail()
    if progress["state"] in {"checkpoint_saved", "final_applied"}:
        checkpoint, _ = recovery._decode_translation_checkpoint(run.raw_response.get(recovery.RESULT_KEY),
            run.article_id, run.pk, run.raw_response[recovery.CLAIM_KEY]["claimed_at"], provenance=_provenance(controls))
        # 仅私有typed codec接纳由程序写入的provenance；普通codec仍拒绝外部注入。
        provenance = checkpoint["metadata"].get(PROVENANCE_KEY)
        if provenance != {"schema_version": 1, "plan_sha256": controls[PLAN_KEY]["payload_sha256"],
                "read_step_uuid": reference["step_uuid"], "read_result_sha256": reference["result_sha256"],
                "input_sha256": identity["input_sha256"]}:
            _fail()
    if FINAL_KEY in controls:
        if (run.status != "success" or controls[FINAL_KEY]["payload"]["checkpoint_sha256"]
                != run.raw_response[recovery.RESULT_KEY]["payload_sha256"]):
            _fail()


def register_offline_readonly_translation_job(envelope):
    binding, scope, sdk = _dependencies()
    with transaction.atomic():
        parent, root, article, run, identity = _locked_registration_context(binding, scope, sdk, envelope, phases="claimed")
        if has_registered_job(run.raw_response):
            controls = decode_control(run.raw_response)
            if controls[PLAN_KEY]["payload"]["identity"] != identity:
                _fail("registered_scope_mismatch")
            _validate_live_controls(controls, parent, root, run)
            return controls[PLAN_KEY]
        if recovery.RESULT_KEY in run.raw_response or parent.request_attempts.exists() or root.steps.exists():
            _fail("registered_plan_invalid")
        payload = {"plan_uuid": str(uuid4()), "job_kind": "readonly_translation_retry_v1",
                   "plan_origin": "program_fixed_translation_retry_v1", "identity": identity,
                   "steps": FIXED_STEPS, "limits": FIXED_LIMITS}
        plan = {"schema_version": 1, "payload": payload, "payload_sha256": _sha(payload)}
        progress = {"schema_version": 1, "plan_sha256": plan["payload_sha256"], "revision": 0, "state": "registered",
                    "model_owner_token": None, "owner_binding_sha256": None, "last_provider_attempt_index": 0,
                    "read_reference": None, "exit_reason": None}
        raw = {**run.raw_response, PLAN_KEY: plan, PROGRESS_KEY: progress}
        controls = decode_control(raw)
        run.raw_response = {**run.raw_response, **controls}
        run.save(update_fields=["raw_response", "updated_at"])
    return controls[PLAN_KEY]


def prepare_registered_read_phase(envelope):
    """E02实际断点前置：只claimed→executing；不执行读/model/save/final。"""
    binding, scope, sdk = _dependencies()
    with transaction.atomic():
        parent, root, article, run, identity = _locked_registration_context(binding, scope, sdk, envelope, phases="claimed")
        controls = decode_control(run.raw_response)
        if controls[PLAN_KEY]["payload"]["identity"] != identity or controls[PROGRESS_KEY]["state"] != "registered":
            _fail("registered_scope_mismatch")
        _validate_live_controls(controls, parent, root, run)
        if parent.request_attempts.exists() or root.steps.exists() or recovery.RESULT_KEY in run.raw_response:
            _fail("registered_plan_invalid")
        run.raw_response = {**run.raw_response, recovery.CLAIM_KEY: {
            **run.raw_response[recovery.CLAIM_KEY], "phase": "executing", "suppress_automation": True}}
        run.prompt_excerpt = (article.body_ja_normalized or article.body_ja_raw)[:800]
        run.save(update_fields=["raw_response", "prompt_excerpt", "updated_at"])
    return article, run


def route_registered_job(article_id, run_id, claimed_at, job_uuid=""):
    """None仅confirmed never-registered；登记任务进入私有consumer，绝不fallback。"""
    if type(article_id) is not int or article_id <= 0 or type(job_uuid) is not str:
        return "registered_message_invalid"
    if run_id is not None and (type(run_id) is not int or run_id <= 0):
        return "registered_message_invalid"
    run = TranslationRun.objects.filter(pk=run_id, article_id=article_id).first() if run_id is not None else None
    registered = run is not None and has_registered_job(run.raw_response)
    if not registered:
        if job_uuid or registered_article_pending(article_id):
            return "registered_message_invalid"
        return None
    try:
        if type(claimed_at) is not str or not claimed_at:
            _fail("registered_message_invalid")
        controls = decode_control(run.raw_response)
        identity = controls[PLAN_KEY]["payload"]["identity"]
        if (identity["run_id"] != run_id or identity["article_id"] != article_id
                or identity["claimed_at"] != _iso(datetime.fromisoformat(claimed_at))
                or (job_uuid and job_uuid != controls[PLAN_KEY]["payload"]["plan_uuid"])):
            _fail("registered_message_invalid")
        binding, scope, sdk = _dependencies()
        # Validate exact scope/read identity under original lock order, with no state mutation.
        with transaction.atomic():
            parent, root, _, locked_run, current = _locked_registration_context(
                binding, scope, sdk, ro.ReadEnvelope(article_id, run_id, claimed_at), phases=("claimed", "executing"),
                allow_completed=controls[PROGRESS_KEY]["state"] == "final_applied")
            locked = decode_control(locked_run.raw_response)
            if locked != controls or current != identity:
                _fail("registered_scope_mismatch")
            _validate_live_controls(locked, parent, root, locked_run)
        return _consume_registered_job(ro.ReadEnvelope(article_id, run_id, claimed_at))
    except (RegisteredJobRefusal, ro.ReadonlyRefusal) as exc:
        return str(exc)
    except (ValueError, TypeError) as exc:
        return "registered_message_invalid"


def _live(envelope, dependencies, *, phases="executing", allow_completed=False):
    """事务外scope前置在调用方；这里始终沿parent→read→Article→Run→step→request锁序。"""
    binding, scope, sdk = dependencies
    parent, root, article, run, identity = _locked_registration_context(
        binding, scope, sdk, envelope, phases=phases, allow_completed=allow_completed)
    controls = decode_control(run.raw_response)
    if controls[PLAN_KEY]["payload"]["identity"] != identity:
        _fail("registered_scope_mismatch")
    _validate_live_controls(controls, parent, root, run)
    return binding, scope, sdk, parent, root, article, run, controls


def _check_deadline_locked(controls):
    now = core._actual_now(timezone.now())
    if now >= datetime.fromisoformat(controls[PLAN_KEY]["payload"]["identity"]["deadline_at"]):
        _fail("deadline_expired")
    return now


def _advance(run, controls, *, state, **fields):
    """锁内CAS完整旧raw；plan不变，revision单调，失败回滚同txn内其他writer。"""
    _check_deadline_locked(controls)
    old = run.raw_response
    progress = {**controls[PROGRESS_KEY], **fields, "state": state,
                "revision": controls[PROGRESS_KEY]["revision"] + 1}
    raw = {**old, PROGRESS_KEY: progress}
    decode_control(raw)
    changed = TranslationRun.objects.filter(pk=run.pk, raw_response=old).update(raw_response=raw, updated_at=timezone.now())
    if changed != 1:
        _fail("registered_progress_conflict")
    run.raw_response = raw
    return decode_control(raw)


def _provenance(controls):
    read = controls[PROGRESS_KEY]["read_reference"]
    return {"schema_version": 1, "plan_sha256": controls[PLAN_KEY]["payload_sha256"],
            "read_step_uuid": read["step_uuid"], "read_result_sha256": read["result_sha256"],
            "input_sha256": controls[PLAN_KEY]["payload"]["identity"]["input_sha256"]}


def _private_checkpoint(payload, controls, envelope):
    return recovery._decode_translation_checkpoint(payload, envelope.article_id, envelope.run_id,
                                                   envelope.claimed_at, provenance=_provenance(controls))


def _read_ready(envelope):
    """原reader在锁外执行；E02已提交ledger可免费复用，不重复claimed prepare。"""
    dependencies = _dependencies()
    with transaction.atomic():
        *_, article, run, controls = _live(envelope, dependencies, phases=("claimed", "executing"))
        state = controls[PROGRESS_KEY]["state"]
        if state not in {"registered", "read_ready"}:
            _fail("model_start_unknown" if state == "model_started" else "registered_progress_not_readable")
        claimed = run.raw_response[recovery.CLAIM_KEY]["phase"] == "claimed"
    if claimed:
        prepare_registered_read_phase(envelope)
    decision = ro.execute_step(envelope, {"body_chars": 256}, now=timezone.now())
    if not decision.allowed:
        if decision.reason == "step_result_unknown":
            _block_unknown_read(envelope)
        _fail(decision.reason)
    dependencies = _dependencies()
    with transaction.atomic():
        _, _, _, _, root, article, run, controls = _live(envelope, dependencies)
        state = controls[PROGRESS_KEY]["state"]
        step = root.steps.get()
        reference = {"step_uuid": str(step.step_uuid), "result_sha256": step.result_sha256}
        if state == "registered":
            controls = _advance(run, controls, state="read_ready", read_reference=reference)
        elif state != "read_ready" or controls[PROGRESS_KEY]["read_reference"] != reference:
            _fail("registered_progress_conflict")
        material = json.loads(ro._json_bytes(step.result))
    return article, run, controls, material


class _ModelInvocation:
    """仅本invocation可消费的私有owner；持久owner不赋予fresh invocation许可。"""
    def __init__(self, envelope, controls):
        binding, scope, sdk = _dependencies()
        self.envelope = envelope
        self.plan_sha = controls[PLAN_KEY]["payload_sha256"]
        self.owner = str(uuid4())
        self.scope_nonce = binding.scope_nonce
        self.read_nonce = scope.nonce
        self.process_thread = (os.getpid(), get_ident())
        self.sdk = sdk
        self.binding_sha = _sha({"plan_sha256": self.plan_sha, "model_owner_token": self.owner,
                                 "parent_scope_nonce": str(self.scope_nonce), "read_scope_nonce": str(self.read_nonce),
                                 "pid": os.getpid(), "thread": get_ident()})
        self.index = 0

    def authorize(self):
        from django.db import DatabaseError
        try:
            return self._authorize()
        except DatabaseError as exc:
            raise recovery.ManagedTranslationAuditFailure("reserve") from exc

    def _authorize(self):
        from django.db import connection
        if connection.in_atomic_block:
            _fail("outer_transaction_forbidden")
        binding, scope, sdk = _dependencies()
        if (sdk is not self.sdk or binding.scope_nonce != self.scope_nonce or scope.nonce != self.read_nonce
                or self.process_thread != (os.getpid(), get_ident())):
            _fail("registered_scope_mismatch")
        index = self.index + 1
        if index > 2:
            _fail("request_limit_exhausted")
        dependencies = (binding, scope, sdk)
        with transaction.atomic():
            binding, _, _, parent, root, article, run, controls = _live(self.envelope, dependencies)
            progress = controls[PROGRESS_KEY]
            if controls[PLAN_KEY]["payload_sha256"] != self.plan_sha:
                _fail("registered_scope_mismatch")
            if index == 1:
                if progress["state"] != "read_ready" or progress["model_owner_token"] is not None:
                    _fail("model_start_unknown")
            elif (progress["state"] != "model_started" or progress["model_owner_token"] != self.owner
                  or progress["owner_binding_sha256"] != self.binding_sha
                  or progress["last_provider_attempt_index"] != self.index):
                _fail("model_start_unknown")
            claim_uuid, reason = recovery._claim_uuid_history_reason(parent, article, run, self.envelope.claimed_at, index)
            if reason:
                _fail(reason)
            identity = recovery._active_bound_identity(article, binding)
            reason = recovery._bound_admission(parent, identity, binding, core._actual_now(timezone.now()))
            if reason:
                _fail(reason)
            attempt, reason = core._reserve_locked(parent, identity, claim_execution_uuid=claim_uuid,
                claimed_at=datetime.fromisoformat(self.envelope.claimed_at), provider_attempt_index=index,
                run_pk_snapshot=run.pk, now=timezone.now(), effective_deadline=datetime.fromisoformat(
                    controls[PLAN_KEY]["payload"]["identity"]["deadline_at"]))
            if reason != "request_reserved":
                _fail(reason)
            _advance(run, controls, state="model_started", model_owner_token=self.owner,
                     owner_binding_sha256=self.binding_sha, last_provider_attempt_index=index)
            deadline = datetime.fromisoformat(controls[PLAN_KEY]["payload"]["identity"]["deadline_at"])
            decision = core._decision(reason, parent, attempt, allowed=True)
        # 唯一授权提交点已完成；slot/CAS提交但create前退出也绝不接管。
        self.index = index
        return decision, deadline, binding


def _registered_provider(invocation, material, provenance):
    from . import translation
    from django.conf import settings
    from django.db import DatabaseError

    class RegisteredProvider(translation.OpenAICompatibleTranslationProvider):
        def _build_messages(self, *args, **kwargs):
            messages = super()._build_messages(*args, **kwargs)
            return messages + [{"role": "user", "content": json.dumps({
                "program_read_evidence": {"material": material, "provenance": provenance}}, ensure_ascii=False)}]

        def _request_completion(self, messages):
            decision, deadline, binding = invocation.authorize()
            remaining = (deadline - core._actual_now(timezone.now())).total_seconds()
            if remaining <= 0:
                _fail("deadline_expired")
            response = invocation.sdk.chat.completions.create(model=settings.TRANSLATION_MODEL,
                temperature=0, response_format={"type": "json_object"}, messages=messages,
                max_tokens=settings.TRANSLATION_MAX_TOKENS,
                timeout=min(settings.TRANSLATION_TIMEOUT_SECONDS, remaining))
            # 先忠实journal，即使返回前已撤权/超期；journal不授予save/final权限。
            try:
                report = self._usage_to_dict(getattr(response, "usage", None))
                audit = core.record_usage(budget_pk=decision.budget_pk, attempt_pk=decision.attempt_pk,
                                          mode=binding.mode, usage_report=report)
                if audit.reason not in {"usage_unknown", "cost_unreconciled", "offline_usage_reconciled", "usage_already_recorded"}:
                    raise recovery.ManagedTranslationAuditFailure("usage", decision.budget_pk, decision.attempt_pk)
            except DatabaseError as exc:
                raise recovery.ManagedTranslationAuditFailure("usage", decision.budget_pk, decision.attempt_pk) from exc
            return response

    return RegisteredProvider(api_key="", base_url="", provider_name="offline-synthetic", offline_client=invocation.sdk)


def _save_registered_checkpoint(envelope, result, invocation):
    # Provider metadata全次拒绝reserved键；程序provenance只走此typed私有路径。
    metadata = business_metadata(result.metadata)
    dependencies = _dependencies()
    with transaction.atomic():
        _, _, _, parent, _, article, run, controls = _live(envelope, dependencies)
        progress = controls[PROGRESS_KEY]
        if (progress["state"] != "model_started" or progress["model_owner_token"] != invocation.owner
                or progress["owner_binding_sha256"] != invocation.binding_sha
                or progress["last_provider_attempt_index"] != invocation.index):
            _fail("model_start_unknown")
        if any(a.usage_validation != "known" for a in parent.request_attempts.all()):
            _fail("usage_unknown")
        claim = run.raw_response[recovery.CLAIM_KEY]
        payload = {"schema_version": 1, "application_contract_version": recovery.RESULT_CONTRACT,
            "article_id": article.pk, "run_id": run.pk, "claimed_at": claim["claimed_at"],
            "input_sha256": claim["input_sha256"], "deadline_at": claim["deadline_at"],
            "checkpoint_at": timezone.now().isoformat(), "title_zh": result.title_zh, "body_zh": result.body_zh,
            "push_summary_zh": result.push_summary_zh, "metadata": {**metadata, PROVENANCE_KEY: _provenance(controls)},
            "suppress_automation": True, "usage_report": metadata.get("usage"), "usage_reconciliation": "unreconciled"}
        payload["payload_sha256"] = hashlib.sha256(recovery._checkpoint_json(payload)).hexdigest()
        checkpoint, _ = _private_checkpoint(payload, controls, envelope)
        if recovery.RESULT_KEY in run.raw_response:
            _fail("checkpoint_invalid")
        run.raw_response = {**run.raw_response, recovery.RESULT_KEY: checkpoint}
        run.save(update_fields=["raw_response", "updated_at"])
        _advance(run, controls, state="checkpoint_saved")
    return checkpoint


def _apply_registered_checkpoint(envelope):
    """免费续apply；当前read grant、真实ledger和Article/Run/final写入处于同txn。"""
    from stable.models import TranslationStatus
    dependencies = _dependencies()
    with transaction.atomic():
        _, _, _, _, _, article, run, controls = _live(envelope, dependencies)
        if controls[PROGRESS_KEY]["state"] != "checkpoint_saved":
            _fail("checkpoint_invalid")
        checkpoint, result = _private_checkpoint(run.raw_response.get(recovery.RESULT_KEY), controls, envelope)
        if not recovery._checkpoint_matches_claim(checkpoint, run.raw_response[recovery.CLAIM_KEY]):
            _fail("checkpoint_invalid")
        now = _check_deadline_locked(controls)
        recovery._apply_translation_result_locked(article, result, now)
        original_raw = run.raw_response
        run.raw_response = {**run.raw_response, **result.metadata, recovery.CLAIM_KEY: {
            **run.raw_response[recovery.CLAIM_KEY], "phase": "completed"}}
        run.status = TranslationStatus.SUCCESS
        run.error_message = ""
        run.model_name = result.metadata.get("model", "")
        run.provider_name = result.metadata.get("provider", "")
        run.terms_used = result.metadata.get("terms", run.terms_used)
        identity = controls[PLAN_KEY]["payload"]["identity"]
        reference = controls[PROGRESS_KEY]["read_reference"]
        payload = {"plan_sha256": controls[PLAN_KEY]["payload_sha256"], "claim_execution_uuid": identity["claim_execution_uuid"],
            "article_id": article.pk, "run_id": run.pk, "checkpoint_sha256": checkpoint["payload_sha256"],
            "read_step_uuid": reference["step_uuid"], "read_result_sha256": reference["result_sha256"], "applied_at": _iso(now)}
        final = {"schema_version": 1, "payload": payload, "payload_sha256": _sha(payload)}
        run.raw_response = {**run.raw_response, FINAL_KEY: final}
        # Persist progress with final as one typed write; decode rejects transient final/state mismatch.
        progress = controls[PROGRESS_KEY]
        run.raw_response[PROGRESS_KEY] = {**progress, "state": "final_applied", "revision": progress["revision"] + 1}
        decode_control(run.raw_response)
        _check_deadline_locked(controls)
        changed = TranslationRun.objects.filter(pk=run.pk, raw_response=original_raw).update(
            raw_response=run.raw_response, status=run.status, error_message=run.error_message,
            model_name=run.model_name, provider_name=run.provider_name, terms_used=run.terms_used, updated_at=now)
        if changed != 1:
            _fail("registered_progress_conflict")
    return {"article_id": article.pk, "translated": True, "final_receipt": final}


def _block_owned_invocation(invocation, reason):
    """仅当前owner可记gap；并发败者/缺scope或撤权不改赢家状态。"""
    if invocation.index == 0:
        return
    dependencies = _dependencies()
    with transaction.atomic():
        *_, run, controls = _live(invocation.envelope, dependencies)
        progress = controls[PROGRESS_KEY]
        if (progress["state"] == "model_started" and progress["model_owner_token"] == invocation.owner
                and progress["owner_binding_sha256"] == invocation.binding_sha):
            _advance(run, controls, state="blocked_unknown" if reason in UNKNOWN_REASONS else "blocked_fence", exit_reason=reason)


def _consume_registered_job(envelope):
    dependencies = _dependencies()
    with transaction.atomic():
        *_, controls = _live(envelope, dependencies, phases=("claimed", "executing"), allow_completed=True)
        state = controls[PROGRESS_KEY]["state"]
        if state == "final_applied":
            # _live已核对当前scope/grant/deadline/identity、真实read/request ledger及原完成归属。
            _check_deadline_locked(controls)
            return {"article_id": envelope.article_id, "translated": False, "skipped": True,
                    "reason": "claim_already_consumed", "final_receipt": controls[FINAL_KEY]}
    if state == "checkpoint_saved":
        return _apply_registered_checkpoint(envelope)
    if state == "model_started" or state.startswith("blocked_"):
        _fail(controls[PROGRESS_KEY]["exit_reason"] or "model_start_unknown")
    article, run, controls, material = _read_ready(envelope)
    invocation = _ModelInvocation(envelope, controls)
    from . import translation
    resolution = translation.resolve_article_entities_for_article(article)
    provider = _registered_provider(invocation, material, _provenance(controls))
    try:
        result = provider.translate(article, entity_resolution=resolution)
        from django.db import DatabaseError
        try:
            _save_registered_checkpoint(envelope, result, invocation)
        except DatabaseError as exc:
            raise recovery.ManagedTranslationAuditFailure("checkpoint") from exc
    except Exception as exc:
        if isinstance(exc, (RegisteredJobRefusal, ro.ReadonlyRefusal)):
            reason = str(exc)
        elif isinstance(exc, TimeoutError):
            reason = "model_start_unknown"
        elif isinstance(exc, recovery.ManagedTranslationAuditFailure):
            # 保留stage和原DatabaseError cause；既有model/slot占用不清除。
            raise
        elif isinstance(exc, (translation.TranslationResponseError, ValueError)):
            reason = "model_refused"
        else:
            raise
        if reason == core.REPORTED_TOKEN_STOP:
            # 不扩v1 progress枚举；当前owner停止仅记诊断，fresh仍model_start_unknown。
            dependencies = _dependencies()
            with transaction.atomic():
                binding, _, _, parent, _, article, run, current = _live(envelope, dependencies)
                progress = current[PROGRESS_KEY]
                if (progress["state"] != "model_started" or progress["model_owner_token"] != invocation.owner
                        or progress["owner_binding_sha256"] != invocation.binding_sha
                        or progress["last_provider_attempt_index"] != invocation.index):
                    _fail("model_start_unknown")
                identity = recovery._active_bound_identity(article, binding)
                if recovery._bound_admission(parent, identity, binding, core._actual_now(timezone.now())) != reason:
                    _fail("registered_scope_mismatch")
                recovery._record_reported_token_stop_locked(parent, article, run)
        if reason in EXIT_REASONS and reason != "storage_failed":
            _block_owned_invocation(invocation, reason)
        raise RegisteredJobRefusal(reason) from exc
    return _apply_registered_checkpoint(envelope)


def _block_unknown_read(envelope):
    dependencies = _dependencies()
    with transaction.atomic():
        *_, run, controls = _live(envelope, dependencies)
        progress = controls[PROGRESS_KEY]
        if progress["state"] == "registered" and progress["model_owner_token"] is None:
            _advance(run, controls, state="blocked_unknown", exit_reason="read_unknown")

"""私有离线只读step：先提交独立读槽，再事务外有限读取，再提交可重放结果。

不接生产/task/provider。未知执行保留已占槽；fresh scoped invocation只复用
同一持久executing envelope下的已验证结果，不重新prepare、不接管inflight。
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4
import hashlib
import json
import os
from threading import Event, get_ident

from django.db import DatabaseError, connection, models, transaction
from django.db.models.functions import Substr
from django.utils import timezone

from stable.models import ManagedReadonlyTaskBudget, ManagedReadonlyStep, NewsArticle
from . import translation_recovery as recovery, translation_retry_budget as core

WORKFLOW_VERSION = "managed-source-excerpt-v1"
QUERY_VERSION = "source_excerpt_v1"
RESULT_VERSION = "readonly-result-v1"
LOGICAL_STEP = "source_excerpt:1"
RESULT_MAX_BYTES = 8192


class ReadonlyRefusal(ValueError):
    pass


class ReadonlyAuditFailure(RuntimeError):
    def __init__(self, stage):
        super().__init__("readonly_audit_failed:" + stage)
        self.stage = stage


class ReadFixtureExit(BaseException):
    pass


@dataclass(frozen=True)
class ReadEnvelope:
    article_id: int
    run_id: int
    claimed_at: str


@dataclass(frozen=True)
class ReadDecision:
    allowed: bool
    reason: str
    result: dict | None = None
    cached: bool = False
    step_uuid: object = None


@dataclass(frozen=True)
class _ReadScope:
    root_pk: int
    permission_epoch: int
    workflow_version: str
    query_version: str
    result_version: str
    parent_nonce: object
    nonce: object
    owner_pid: int
    owner_thread: int


_read_scope = ContextVar("managed_readonly_scope", default=None)
_read_dependency = ContextVar("managed_readonly_dependency", default=None)


def _parent_binding(now):
    binding = recovery._current_offline_budget_binding()
    if binding is None:
        raise ReadonlyRefusal("readonly_scope_missing")
    refused = core._preflight(binding.mode, binding.identity, now)
    if refused:
        raise ReadonlyRefusal(refused.reason)
    return binding


def _current_scope(now):
    binding = _parent_binding(now)
    scope = _read_scope.get()
    if (type(scope) is not _ReadScope or scope.parent_nonce != binding.scope_nonce
            or scope.owner_pid != os.getpid() or scope.owner_thread != get_ident()):
        raise ReadonlyRefusal("readonly_scope_mismatch")
    return binding, scope


@contextmanager
def readonly_scope(root_pk, *, workflow_version=None, query_version=None, result_version=None):
    binding = _parent_binding(timezone.now())
    if _read_scope.get() is not None or type(root_pk) is not int or root_pk <= 0:
        raise ReadonlyRefusal("readonly_scope_mismatch")
    root = ManagedReadonlyTaskBudget.objects.filter(pk=root_pk).first()
    if root is None or root.operation_uuid != binding.identity.operation_uuid:
        raise ReadonlyRefusal("readonly_scope_mismatch")
    versions = (WORKFLOW_VERSION if workflow_version is None else workflow_version,
                QUERY_VERSION if query_version is None else query_version,
                RESULT_VERSION if result_version is None else result_version)
    if any(type(v) is not str or not 0 < len(v) <= 64 for v in versions):
        raise ReadonlyRefusal("readonly_scope_mismatch")
    token = _read_scope.set(_ReadScope(root.pk, root.permission_epoch, *versions,
        binding.scope_nonce, uuid4(), os.getpid(), get_ident()))
    try:
        yield _read_scope.get()
    finally:
        _read_scope.reset(token)


def _parent_identity_valid(parent, identity):
    # Revalidate the bound task identity without provider/request admission: pending SDK cost is separate.
    if (core._identity_reason(parent, identity)
            or identity.article_pk_snapshot != parent.article_pk_snapshot
            or identity.source_sha256 != parent.source_sha256):
        raise ReadonlyRefusal("read_identity_changed")


def initialize_read_budget(*, tool_read_limit, baseline, now):
    binding = _parent_binding(now)
    if (type(tool_read_limit) is not int or tool_read_limit not in (0, 1, 2)
            or type(baseline) is not dict or baseline != {
                "kind": "synthetic_no_prior_tool_reads", "operation_uuid": str(binding.identity.operation_uuid)}):
        raise ReadonlyRefusal("readonly_baseline_unknown")
    with transaction.atomic():
        parent, reason = core._locked_root(binding.identity)
        if parent is None or reason:
            raise ReadonlyRefusal(reason or "budget_missing")
        _parent_identity_valid(parent, binding.identity)
        if parent.retired_at is not None:
            raise ReadonlyRefusal("read_identity_changed")
        if core._actual_now(now) >= parent.deadline_at:
            raise ReadonlyRefusal("read_deadline_expired")
        existing = ManagedReadonlyTaskBudget.objects.filter(parent_budget=parent).first()
        if existing:
            if existing.tool_read_limit != tool_read_limit:
                raise ReadonlyRefusal("read_budget_contract_changed")
            return existing
        return ManagedReadonlyTaskBudget.objects.create(parent_budget=parent,
            operation_uuid=parent.operation_uuid, read_budget_uuid=uuid4(),
            article_pk_snapshot=parent.article_pk_snapshot, source_site_snapshot=parent.source_site_snapshot,
            source_article_id_snapshot=parent.source_article_id_snapshot, source_sha256=parent.source_sha256,
            workflow_version=WORKFLOW_VERSION, query_version=QUERY_VERSION, result_version=RESULT_VERSION,
            permission_epoch=1, allowed_tools=[QUERY_VERSION], opened_at=parent.opened_at,
            deadline_at=parent.deadline_at, tool_read_limit=tool_read_limit)


def _params(params):
    if (type(params) is not dict or set(params) != {"body_chars"}
            or type(params["body_chars"]) is not int or params["body_chars"] not in (256, 512)):
        raise ReadonlyRefusal("readonly_params_invalid")
    return {"body_chars": params["body_chars"]}


def _envelope_valid(envelope):
    if (type(envelope) is not ReadEnvelope or type(envelope.article_id) is not int
            or type(envelope.run_id) is not int or not 0 < envelope.article_id <= 9223372036854775807
            or not 0 < envelope.run_id <= 9223372036854775807
            or type(envelope.claimed_at) is not str):
        raise ReadonlyRefusal("claim_missing")


def _locked_context(binding, scope, envelope, now):
    """调用方已完成preflight并持短atomic；parent→readonly root→Article→Run。"""
    parent, reason = core._locked_root(binding.identity)
    if parent is None or reason:
        raise ReadonlyRefusal(reason or "budget_missing")
    _parent_identity_valid(parent, binding.identity)
    root = ManagedReadonlyTaskBudget.objects.select_for_update().filter(pk=scope.root_pk).first()
    if root is None:
        raise ReadonlyRefusal("readonly_scope_mismatch")
    if root.parent_budget_id != parent.pk or root.operation_uuid != parent.operation_uuid:
        raise ReadonlyRefusal("readonly_scope_mismatch")
    if (parent.retired_at is not None or
            (root.article_pk_snapshot, root.source_site_snapshot, root.source_article_id_snapshot,
             root.source_sha256, root.opened_at, root.deadline_at) !=
            (parent.article_pk_snapshot, parent.source_site_snapshot, parent.source_article_id_snapshot,
             parent.source_sha256, parent.opened_at, parent.deadline_at)):
        raise ReadonlyRefusal("read_identity_changed")
    article, run, reason = recovery._locked_translation_claim(envelope.article_id, envelope.run_id,
        envelope.claimed_at, phase="executing", now=now)
    if reason:
        raise ReadonlyRefusal(reason)
    claim = run.raw_response[recovery.CLAIM_KEY]
    try:
        claim_uuid = claim["claim_execution_uuid"]
        if type(claim_uuid) is not str or str(UUID(claim_uuid)) != claim_uuid:
            raise ValueError("noncanonical claim UUID")
    except (KeyError, ValueError, TypeError) as exc:
        raise ReadonlyRefusal("read_identity_changed") from exc
    if (article.pk != root.article_pk_snapshot or (article.source_site, article.source_article_id) !=
            (root.source_site_snapshot, root.source_article_id_snapshot)
            or claim.get("budget_uuid") != str(parent.budget_uuid)
            or claim.get("budget_operation_uuid") != str(parent.operation_uuid)
            or not claim.get("claim_execution_uuid")):
        raise ReadonlyRefusal("read_identity_changed")
    if recovery.translation_input_sha256(article) != root.source_sha256:
        raise ReadonlyRefusal("input_changed")
    if (root.workflow_version, root.query_version, root.result_version) != (
            scope.workflow_version, scope.query_version, scope.result_version) or (
            scope.workflow_version, scope.query_version, scope.result_version) != (
            WORKFLOW_VERSION, QUERY_VERSION, RESULT_VERSION):
        raise ReadonlyRefusal("step_version_changed")
    if root.state == "revoked" or root.permission_epoch != scope.permission_epoch or root.allowed_tools != [QUERY_VERSION]:
        raise ReadonlyRefusal("read_permission_revoked")
    if root.state != "open":
        raise ReadonlyRefusal("read_root_unavailable")
    deadline = min(root.deadline_at, datetime.fromisoformat(claim["deadline_at"]))
    if core._actual_now(now) >= deadline:
        raise ReadonlyRefusal("read_deadline_expired")
    return root, {"operation_uuid": str(parent.operation_uuid), "parent_budget_uuid": str(parent.budget_uuid),
        "read_budget_uuid": str(root.read_budget_uuid), "article_id": article.pk, "run_id": run.pk,
        "claimed_at": claim["claimed_at"], "claim_execution_uuid": claim["claim_execution_uuid"],
        "source_site": article.source_site, "source_article_id": article.source_article_id,
        "input_sha256": root.source_sha256, "deadline_at": deadline.isoformat(),
        "workflow_version": scope.workflow_version, "query_version": scope.query_version,
        "result_version": scope.result_version, "permission_epoch": scope.permission_epoch}


def revoke_read_grant(root_pk):
    _current_scope(timezone.now())
    with transaction.atomic():
        root = ManagedReadonlyTaskBudget.objects.select_for_update().get(pk=root_pk)
        if root.pk != _read_scope.get().root_pk:
            raise ReadonlyRefusal("readonly_scope_mismatch")
        if root.state != "revoked":
            models.QuerySet.update(ManagedReadonlyTaskBudget.objects.filter(pk=root.pk),
                state="revoked", permission_epoch=root.permission_epoch + 1, blocked_reason="grant_revoked")


def _read_source_excerpt_once(envelope, params, expected):
    # 同一条有限SELECT返回用于digest的真实源字段和摘录材料，不能把另外一次hash贴给旧摘录。
    raw_body = models.Q(body_ja_normalized="") | models.Q(body_ja_normalized__isnull=True)
    body = models.Case(models.When(raw_body, then=models.F("body_ja_raw")), default=models.F("body_ja_normalized"))
    field = models.Case(models.When(raw_body, then=models.Value("body_ja_raw")), default=models.Value("body_ja_normalized"))
    row = NewsArticle.objects.filter(pk=envelope.article_id).annotate(
        _ro_title=Substr("title_ja", 1, 65537), _ro_body=Substr(body, 1, 65537), _ro_field=field,
    ).values("pk", "source_site", "source_article_id", "source_language", "_ro_title", "_ro_body", "_ro_field").first()
    if row is None or len(row["_ro_title"]) > 65536 or len(row["_ro_body"]) > 65536:
        raise ReadonlyRefusal("read_source_missing_or_oversized")
    snapshot = SimpleNamespace(source_site=row["source_site"], source_language=row["source_language"],
        title_ja=row["_ro_title"], body_ja_normalized=row["_ro_body"] if row["_ro_field"] == "body_ja_normalized" else "",
        body_ja_raw=row["_ro_body"])
    actual_sha = recovery.translation_input_sha256(snapshot)
    if ((row["source_site"], row["source_article_id"]) != (expected["source_site"], expected["source_article_id"])
            or actual_sha != expected["input_sha256"]):
        raise ReadonlyRefusal("read_snapshot_changed")
    result = {"query_version": QUERY_VERSION, "result_version": RESULT_VERSION,
        "article_id": row["pk"], "run_id": envelope.run_id, "source_site": row["source_site"],
        "source_article_id": row["source_article_id"], "input_sha256": actual_sha,
        "title": row["_ro_title"][:256], "body_excerpt": row["_ro_body"][:params["body_chars"]],
        "body_chars": params["body_chars"], "read_at": timezone.now().isoformat()}
    if len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) > RESULT_MAX_BYTES:
        raise ReadonlyRefusal("read_result_oversized")
    return result


class _ClosedSourceExcerptReader:
    __slots__ = ("fault", "trace", "owner", "closed", "before_read_ready", "before_read_release")

    def __init__(self, fault="none"):
        if type(fault) is not str or fault not in {"none", "timeout_before_read", "timeout_after_read",
                "exit_after_reservation", "exit_after_read", "exit_after_commit", "revoke_after_read", "pause_before_read", "change_before_read"}:
            raise ReadonlyRefusal("read_dependency_invalid")
        self.fault, self.trace, self.owner, self.closed = fault, [], None, False
        self.before_read_ready, self.before_read_release = Event(), Event()

    def read(self, envelope, params, expected, reservation):
        _read_permit_guard(envelope, params, expected, reservation)
        scope = _read_scope.get()
        if scope is None or self.closed or self.owner != (scope.nonce, os.getpid(), get_ident()):
            raise ReadonlyRefusal("read_dependency_mismatch")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            backend_pid = cursor.fetchone()[0]
        self.trace.append({"event": "before_read", "backend_pid": backend_pid, "in_atomic": connection.in_atomic_block,
            "reserved": ManagedReadonlyTaskBudget.objects.get(pk=scope.root_pk).tool_reads_reserved,
            "inflight_count": ManagedReadonlyStep.objects.filter(read_budget_id=scope.root_pk, state="inflight").count()})
        if self.fault == "pause_before_read":
            self.before_read_ready.set()
            if not self.before_read_release.wait(8):
                raise TimeoutError("fixture observation release missing")
        if self.fault == "timeout_before_read":
            raise TimeoutError("synthetic read timeout before SQL")
        if self.fault == "change_before_read":
            NewsArticle.objects.filter(pk=envelope.article_id).update(title_ja="synthetic source changed at query boundary")
        event = {"event": "business_read", "input_sha256": None}
        self.trace.append(event)
        result = _read_source_excerpt_once(envelope, params, expected)
        event["input_sha256"] = result["input_sha256"]
        if self.fault == "timeout_after_read":
            raise TimeoutError("synthetic read timeout after SQL")
        if self.fault == "exit_after_read":
            raise ReadFixtureExit("read exited before step save")
        if self.fault == "revoke_after_read":
            revoke_read_grant(scope.root_pk)
        return result


@contextmanager
def reader_dependency(reader):
    _, scope = _current_scope(timezone.now())
    if type(reader) is not _ClosedSourceExcerptReader or reader.closed or _read_dependency.get() is not None:
        raise ReadonlyRefusal("read_dependency_invalid")
    reader.owner = (scope.nonce, os.getpid(), get_ident())
    token = _read_dependency.set(reader)
    try:
        yield reader
    finally:
        reader.closed = True
        _read_dependency.reset(token)


@dataclass(frozen=True)
class _ReadReservation:
    root_pk: int
    step_pk: int
    step_uuid: UUID
    token: UUID
    contract_sha256: str
    identity_json: bytes
    scope_nonce: UUID
    owner_pid: int
    owner_thread: int


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _identity_bytes(value):
    """Exact JSON types and canonical bytes: bool/int and float/int are distinct identities."""
    def validate(item):
        kind = type(item)
        if kind is dict:
            if any(type(key) is not str for key in item):
                raise TypeError("non-string identity key")
            for child in item.values():
                validate(child)
        elif kind is list:
            for child in item:
                validate(child)
        elif kind not in (str, int, bool, float, type(None)):
            raise TypeError("non-JSON identity type")
    try:
        validate(value)
        return _json_bytes(value)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ReadonlyRefusal("step_identity_changed") from exc


def _contract(expected, params):
    # Fresh nonce is deliberately excluded: the stored logical identity must survive a fresh scope.
    return {"identity": expected, "params": params, "logical_step": LOGICAL_STEP, "tool": QUERY_VERSION}


def _step_identity(step, expected, params):
    contract_bytes = _identity_bytes(_contract(expected, params))
    stored_bytes = _identity_bytes(step.envelope)
    if (step.logical_step_name != LOGICAL_STEP or stored_bytes != contract_bytes
            or hashlib.sha256(stored_bytes).hexdigest() != step.idempotency_sha256
            or step.params_sha256 != _sha(params)
            or type(step.step_uuid) is not UUID or type(step.reservation_token) is not UUID):
        raise ReadonlyRefusal("step_identity_changed")


def _validated_result(step, expected, params):
    result = step.result
    fields = {"query_version", "result_version", "article_id", "run_id", "source_site", "source_article_id",
              "input_sha256", "title", "body_excerpt", "body_chars", "read_at", "step_uuid", "idempotency_sha256"}
    if type(result) is not dict or set(result) != fields:
        raise ReadonlyRefusal("step_result_invalid")
    required = {"query_version": expected["query_version"], "result_version": expected["result_version"],
                "article_id": expected["article_id"], "run_id": expected["run_id"],
                "source_site": expected["source_site"], "source_article_id": expected["source_article_id"],
                "input_sha256": expected["input_sha256"], "body_chars": params["body_chars"],
                "step_uuid": str(step.step_uuid), "idempotency_sha256": step.idempotency_sha256}
    if (any(type(result[k]) is not type(v) or result[k] != v for k, v in required.items())
            or type(result["title"]) is not str or len(result["title"]) > 256
            or type(result["body_excerpt"]) is not str or len(result["body_excerpt"]) > params["body_chars"]
            or type(result["read_at"]) is not str or step.read_at is None or step.completed_at is None):
        raise ReadonlyRefusal("step_result_invalid")
    try:
        read_at = datetime.fromisoformat(result["read_at"])
        deadline = datetime.fromisoformat(expected["deadline_at"])
        encoded = _json_bytes(result)
        valid = (read_at.utcoffset() is not None and read_at == step.read_at
                 and step.reserved_at <= read_at <= step.completed_at < deadline
                 and len(encoded) <= RESULT_MAX_BYTES
                 and hashlib.sha256(encoded).hexdigest() == step.result_sha256)
    except (ValueError, TypeError, OverflowError):
        valid = False
    if not valid:
        raise ReadonlyRefusal("step_result_invalid")
    # Return a detached primitive JSON value; caller mutation cannot become a stored result.
    return json.loads(encoded)


def _admit_step(envelope, params, now):
    binding, scope = _current_scope(now)
    _envelope_valid(envelope)
    with transaction.atomic():
        root, expected = _locked_context(binding, scope, envelope, now)
        step = ManagedReadonlyStep.objects.select_for_update().filter(
            read_budget=root, logical_step_name=LOGICAL_STEP).first()
        if step is not None:
            _step_identity(step, expected, params)
            if step.state == "completed":
                return ReadDecision(True, "step_cached", _validated_result(step, expected, params), True, step.step_uuid)
            # No timeout/exit can prove no read happened. Existing token is never transferred.
            return ReadDecision(False, "step_result_unknown", step_uuid=step.step_uuid)
        if root.tool_reads_reserved >= root.tool_read_limit:
            return ReadDecision(False, "tool_read_limit_exhausted")
        contract = _contract(expected, params)
        reserved_at = core._actual_now(now)
        if reserved_at >= datetime.fromisoformat(expected["deadline_at"]):
            raise ReadonlyRefusal("read_deadline_expired")
        changed = models.QuerySet.update(ManagedReadonlyTaskBudget.objects.filter(
            pk=root.pk, state="open", permission_epoch=scope.permission_epoch,
            tool_reads_reserved=root.tool_reads_reserved), tool_reads_reserved=models.F("tool_reads_reserved") + 1)
        if changed != 1:
            raise ReadonlyRefusal("read_root_unavailable")
        step = ManagedReadonlyStep.objects.create(read_budget=root, step_uuid=uuid4(),
            logical_step_name=LOGICAL_STEP, idempotency_sha256=_sha(contract), envelope=contract,
            params_sha256=_sha(params), reservation_token=uuid4(), reserved_at=reserved_at)
        permit = _ReadReservation(root.pk, step.pk, step.step_uuid, step.reservation_token,
            step.idempotency_sha256, _identity_bytes(expected), scope.nonce, os.getpid(), get_ident())
    # Both the counter and executing ledger must commit before any reader is called.
    return permit


def _read_permit_guard(envelope, params, expected, reservation):
    """只允许已提交且仍归本次scope持有的slot进入固定业务SELECT。"""
    now = timezone.now()
    binding, scope = _current_scope(now)
    _envelope_valid(envelope)
    if (type(reservation) is not _ReadReservation or reservation.scope_nonce != scope.nonce
            or reservation.owner_pid != os.getpid() or reservation.owner_thread != get_ident()
            or reservation.root_pk != scope.root_pk or _identity_bytes(expected) != reservation.identity_json):
        raise ReadonlyRefusal("readonly_scope_mismatch")
    with transaction.atomic():
        root, current = _locked_context(binding, scope, envelope, now)
        step = ManagedReadonlyStep.objects.select_for_update().filter(
            pk=reservation.step_pk, read_budget=root, logical_step_name=LOGICAL_STEP).first()
        if (step is None or step.state != "inflight" or root.tool_reads_reserved < 1
                or step.step_uuid != reservation.step_uuid or step.reservation_token != reservation.token
                or step.idempotency_sha256 != reservation.contract_sha256
                or _identity_bytes(current) != reservation.identity_json):
            raise ReadonlyRefusal("step_result_unknown")
        _step_identity(step, current, params)
    # No atomic/row lock survives into the reader's observation point or business SELECT.


def _finish_step(envelope, params, reservation, result, now):
    binding, scope = _current_scope(now)
    _envelope_valid(envelope)
    if (type(reservation) is not _ReadReservation or reservation.scope_nonce != scope.nonce
            or reservation.owner_pid != os.getpid() or reservation.owner_thread != get_ident()
            or reservation.root_pk != scope.root_pk):
        raise ReadonlyRefusal("readonly_scope_mismatch")
    with transaction.atomic():
        root, expected = _locked_context(binding, scope, envelope, now)
        step = ManagedReadonlyStep.objects.select_for_update().filter(
            pk=reservation.step_pk, read_budget=root, logical_step_name=LOGICAL_STEP).first()
        if step is None:
            raise ReadonlyRefusal("step_result_unknown")
        _step_identity(step, expected, params)
        if (step.state != "inflight" or step.step_uuid != reservation.step_uuid
                or step.reservation_token != reservation.token
                or step.idempotency_sha256 != reservation.contract_sha256):
            raise ReadonlyRefusal("step_result_unknown")
        if type(result) is not dict:
            raise ReadonlyRefusal("step_result_invalid")
        stored = dict(result, step_uuid=str(step.step_uuid), idempotency_sha256=step.idempotency_sha256)
        try:
            step.read_at = datetime.fromisoformat(stored["read_at"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ReadonlyRefusal("step_result_invalid") from exc
        step.completed_at = core._actual_now(now)
        step.result = stored
        step.result_sha256 = _sha(stored)
        validated = _validated_result(step, expected, params)
        changed = models.QuerySet.update(ManagedReadonlyStep.objects.filter(pk=step.pk, state="inflight",
            reservation_token=reservation.token), state="completed", read_at=step.read_at,
            completed_at=step.completed_at, result=stored, result_sha256=step.result_sha256)
        if changed != 1:
            raise ReadonlyRefusal("step_result_unknown")
    # Returning a trusted result is permitted only after the completed-result transaction commits.
    return ReadDecision(True, "step_completed", validated, False, step.step_uuid)


def execute_step(envelope, params, *, now):
    """唯一获准者读一次；缓存重放和unknown拒绝均不再进入业务reader。"""
    stage = "admission"
    try:
        _, scope = _current_scope(now)
        params = _params(params)
        reader = _read_dependency.get()
        if (type(reader) is not _ClosedSourceExcerptReader or reader.closed
                or reader.owner != (scope.nonce, os.getpid(), get_ident())):
            raise ReadonlyRefusal("read_dependency_missing")
        admission = _admit_step(envelope, params, now)
        if type(admission) is ReadDecision:
            return admission
        if reader.fault == "exit_after_reservation":
            raise ReadFixtureExit("read exited after committed tool reservation")
        stage = "source_read"
        # Use the fixed class implementation, never an instance callable or model/client factory.
        result = _ClosedSourceExcerptReader.read(reader, envelope, params,
            json.loads(admission.identity_json), admission)
        stage = "result_commit"
        decision = _finish_step(envelope, params, admission, result, now)
        if reader.fault == "exit_after_commit":
            raise ReadFixtureExit("read exited after committed step result")
        return decision
    except ReadonlyRefusal as exc:
        return ReadDecision(False, str(exc))
    except TimeoutError:
        return ReadDecision(False, "step_result_unknown")
    except DatabaseError as exc:
        # Reservation errors roll back together. Later errors leave the committed slot/inflight intact.
        raise ReadonlyAuditFailure(stage) from exc
